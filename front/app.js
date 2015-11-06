import Mousetrap from 'mousetrap';
import Vue from 'vue';
import createHistory from 'history/lib/createBrowserHistory';
import horsey from 'horsey';
import insignia from 'insignia';
import tabOverride from 'taboverride/build/output/taboverride';

Vue.config.debug = conf.debug;
Vue.config.proto = false;

let array_union = require('lodash/array/union');

let ws, wsTry = 0, handlers = {}, handlerSeq = 0;
let user, view, views = [], tab, sidebar, history;
let initUser = (data, url) => {
    user = data.username ? data : null;
    if (url) go(url);
};
let session = {
    storage: localStorage || {},
    key(key) {
        return `${user.username}_${key}`;
    },
    get(key, none) {
        if (!user || !user.username) return none;
        let val = this.storage[this.key(key)];
        val = val && JSON.parse(val);
        return val !== undefined ? val : none;
    },
    set(key, val) {
        if (!user || !user.username) return;
        this.storage[this.key(key)] = JSON.stringify(val);
    }
};

let offset = new Date().getTimezoneOffset() / 60;
send(`/info/?offset=${offset}`, null, (data) => {
    initUser(data);

    let title = document.title;
    let patterns = [
        ['\/$', () => {
            let first = session.get('tabs', [])[0];
            return first ? go(first.url) : goToLabel('\\Inbox');
        }],
        ['\/(raw)\/', () => {
            location.href = '/api' + location.pathname;
        }],
        ['\/(emails|thread|body)\/', Emails],
        ['\/compose\/', Compose],
        ['\/login\/', Login],
        ['\/pwd\/', Pwd],
    ];
    let initComponent = (current) => {
        send(getPath(), null, {
            success(data) {
                let body = $('.body-active')[0];
                body.scrollTop = 0;
                if (!view || view.constructor != current) {
                    view = new current({data: data, el: body});
                } else {
                    view.$data = data;
                }
                views[tab] = view;

                if (data.title) {
                    document.title = `${data.title} - ${title}`;
                }
                if (sidebar) sidebar.saveTab();
            },
            error: (data) => error(data)
        });
    };
    history = createHistory();
    history.listen((location) => {
        if (user && !sidebar) {
            sidebar = new Sidebar();
        }
        if (user && conf.ws_enabled && !ws) {
            connect();
        }
        if (user && !user.last_sync) {
            new Component({
                template: require('./empty.html'),
                el: '.body-active',
                data: data
            });
            return;
        }
        for (let [pattern, current] of patterns) {
            pattern = '^(/([0-9]+))?' + `(${pattern})`;
            let info = RegExp(pattern).exec(location.pathname);
            if (info) {
                let body, load = true;
                let tabNew = info[2] ? parseInt(info[2]) : 0;
                let tabs = session.get('tabs', []);
                if (tabNew > tabs.length) {
                    tab = tabs.length;
                    go(info[3] + location.search);
                    return;
                }
                if (tab != tabNew) {
                    tab = tabNew;
                    view = views[tab];
                    body = $(`.body-${tab}`);
                    if (body.length) {
                        load = false;
                        body = body[0];
                    } else {
                        body = document.createElement('div');
                        body.classList.add('body', `body-${tab}`);
                        $('body')[0].appendChild(body);
                    }
                    for (let el of Array.from($('.body'))) {
                        el.classList.remove('body-active');
                    }
                    body.classList.add('body-active');
                    if (view && !load) {
                        if (sidebar) sidebar.activate();
                        view.activate();
                        return;
                    }
                }
                if (current.component) {
                    initComponent(current);
                } else {
                    current();
                }
                return;
            }
        }
        error('404 Not Found');
    });
});

/* Keyboard shortcuts */
let hotkeys = [
    [['s a', '* a'], 'Select all conversations', () => {
        filterEmails((i) => view.pick(i, true));
    }],
    [['s n', '* n'], 'Deselect all conversations', () => {
        filterEmails((i) => view.pick(i, false));
    }],
    [['s r', '* r'], 'Select read conversations', () => {
        filterEmails((i) => i.unread || view.pick(i, true));
    }],
    [['s u', '* u'], 'Select unread conversations', () => {
        filterEmails((i) => i.unread && view.pick(i, true));
    }],
    [['s p', '* s'], 'Select pinned conversations', () => {
        filterEmails((i) => i.pinned && view.pick(i, true));
    }],
    [['s shift+p', '* t'], 'Select unpinned conversations', () => {
        filterEmails((i) => i.pinned || view.pick(i, true));
    }],
    [['m !', '!'], 'Report as spam', () => mark({action: '+', name: '\\Spam'})],
    [['m #', '#'] , 'Delete', () => mark({action: '+', name: '\\Trash'})],
    // [['m p'], 'Mark as pinned',
    //     () => mark({action: '+', name: '\\Pinned'})
    // ],
    [['m u', 'm shift+r'], 'Mark as unread',
        () => mark({action: '+', name: '\\Unread'}, () => {})
    ],
    [['m r', 'm shift+u'], 'Mark as read',
        () => mark({action: '-', name: '\\Unread'}, () => {})
    ],
    [['m i', 'm shift+a'], 'Move to Inbox',
        () => mark({action: '+', name: '\\Inbox'})
    ],
    [['m a', 'm shift+i'], 'Move to Archive',
        () => mark({action: '-', name: '\\Inbox'})
    ],
    [['m l'], 'Edit labels', () => $('.labels--edit')[0].click()],
    [['r r'], 'Reply', () => {
        if (view.thread) go(view.last_email.links.reply);
    }],
    [['r a'], 'Reply all', () => {
        if (view.thread) go(view.last_email.links.replyall);
    }],
    [['c'], 'Compose', () => go('/compose/')],
    [['g i'], 'Go to Inbox', () => goToLabel('\\Inbox')],
    [['g d'], 'Go to Drafts', () => goToLabel('\\Drafts')],
    [['g s'], 'Go to Sent messages', () => goToLabel('\\Sent')],
    [['g u'], 'Go to Unread conversations', () => goToLabel('\\Unread')],
    [['g p'], 'Go to Pinned conversations', () => goToLabel('\\Pinned')],
    [['g a'], 'Go to All mail', () => goToLabel('\\All')],
    [['g !'], 'Go to Spam', () => goToLabel('\\Spam')],
    [['g #'], 'Go to Trash', () => goToLabel('\\Trash')],
    [['?'], 'Toggle keyboard shortcut help', () => sidebar.toggleHelp()]
];
Vue.filter('labelUrl', (value) => {
    return '/emails/?q=in:' + escapeQuery(value);
});
Vue.filter('trancate', (value, max) => {
    max = max || 15;
    if (value.length > max) {
        value = value.slice(0, max - 1) + '…';
    }
    return value;
});
let Component = Vue.extend({
    replace: false,
    mixins: [{
        methods: {
            permanent(key) {
                if (this.permanents === undefined) {
                    this.$data.$set('permanents', new Set(['permanents']));
                }
                this.permanents.add(key);
            },
            initData(data) {
                return data;
            },
            go(e, url) {
                if(e) e.preventDefault();
                url = url ? url : e.target.href;
                go(url);
            },
            activate() {}
        },
    }],
});
let p = Component.prototype;
p._initDataOrig = p._initData;
p._initData = function() {
    p._initDataOrig.bind(this)();
    if (this._data && !this.$parent) {
        this._data = this.initData(this._data);
    }
};
p._setDataOrig = p._setData;
p._setData = function(data) {
    if (!this.$parent && data !== undefined) {
        for (let key of this.permanents || []) {
            data.$set(key, this.$data[key]);
        }
        data = this.initData(data);
    }
    p._setDataOrig.bind(this)(data);
};
let Login = Component.extend({
    name: 'Login',
    template: require('./login.html'),
    methods: {
        initData(data) {
            let defaults = {
                username: '',
                password: '',
                greeting: conf.greeting,
                error: null
            };
            for (let key in defaults) {
                if(data[key] === undefined) {
                    data.$set(key, defaults[key]);
                }
            }
            return data;
        },
        submit(e) {
            e.preventDefault();
            api(location.href, {method: 'post'}, {
                username: this.username,
                password: this.password
            })
                .then((data) => {
                    if (data.error) {
                        this.$data = data;
                        return;
                    }
                    initUser(data, '/');
                })
                .catch((data) => {
                    this.error = 'Something went wrong, please try again';
                    this.password = '';
                });
        },
    },
});

let Pwd = Component.extend({
    name: 'Pwd',
    template: require('./pwd.html'),
    methods: {
        initData(data) {
            let defaults = {
                password: '',
                password_confirm: '',
                error: null
            };
            for (let key in defaults) {
                if(data[key] === undefined) {
                    data.$set(key, defaults[key]);
                }
            }
            return data;
        },
        submit(e) {
            e.preventDefault();
            let password = this.password;
            api(location.href, {method: 'post'}, {
                password: password,
                password_confirm: this.password_confirm
            })
                .then((data) => {
                    if (data.error) {
                        this.$data = data;
                        return;
                    }
                    api('/login/', {method: 'post'}, {
                        username: data.username,
                        password: password}
                    ).then((data) => {
                        initUser(data, '/');
                    });
                });
        }
    }
});
let Slider = Component.extend({
    name: 'Slider',
    template: require('./slider.html'),
    data() {
        return {slide: null, slides: []};
    },
    created() {
        this.$mount('.overlay');

        Mousetrap
            .bind('esc', (e => this.close()))
            .bind('left', (e => this.prev()))
            .bind('right', (e => this.next()));
    },
    methods: {
        close(e) {
            if (e) e.preventDefault();
            this.$destroy();
            $('.slider')[0].remove();
            Mousetrap.unbind(['esc', 'left', 'right']);
        },
        prev(e, callback) {
            callback = callback || (i => i - 1);
            for (let v of this.slides) {
                if (v.url == this.slide.url) {
                    this.slide = v;
                    break;
                }
            }
            let i = this.slides.indexOf(this.slide);
            i = callback(i);
            if (i < 0) {
                this.slide = this.slides.splice(-1)[0];
            } else if (i > this.slides.length - 1) {
                this.slide = this.slides[0];
            } else {
                this.slide = this.slides[i];
            }
        },
        next(e) {
            this.prev(e, (i => i + 1));
        },
        fix() {
            let fix = (x, y) => !y ? 0 : Math.round((x - y) / 2) + 'px';
            let box = $('.slider-img')[0], img = box.firstElementChild;
            img.style.maxWidth = box.clientWidth;
            img.style.maxHeight = box.clientHeight;
            img.style.top = fix(box.clientHeight, img.clientHeight);
            img.style.left = fix(box.clientWidth, img.clientWidth);
        }
    }
});
let Sidebar = Component.extend({
    replace: true,
    name: 'Sidebar',
    template: require('./sidebar.html'),
    created() {
        this.fetch((data) => this.$mount('.sidebar'));
        this.setFont(session.get('bigger', false));

        this.help = '';
        for (let item of hotkeys) {
            Mousetrap.bind(item[0], item[2].bind(this), 'keyup');
            this.help += `<div><b>${item[0][0]}</b>: ${item[1]}</div>`;
        }
        this.$watch('labels_sel', () => this.$nextTick(() => {
            if (this.resetLabels === undefined) {
                this.resetLabels = this.initLabels();
            }
            if (this.resetLabels) this.resetLabels();
        }));
        this.$watch('tabs', (val) => {
            session.set('tabs', val);
        });
    },
    computed: {
        showTrash() {
            return this.labels_sel.indexOf('\\Trash') === -1;
        },
        showSpam() {
            return this.labels_sel.indexOf('\\Spam') === -1;
        },
    },
    methods: {
        fetch(callback) {
            let self = this;
            send('/labels/', null, (data) => {
                self.$data = Object.assign({labels: data}, user);
                if (callback) callback(data);
            });
        },
        activate(data) {
            data = data || this;
            data.$set('errors', data.errors || []);
            data.$set('slide', null);

            if (view && view.constructor == Emails) {
                data.$set('search_query', view.search_query);
                data.$set('labels_sel', view.getLabelsByPicked());
                data.$set('labels_edit', (
                    view.getPicked().length > 0 || view.thread ? true : false
                ));
            } else {
                data.$set('search_query', '');
                data.$set('labels_sel', []);
                data.$set('labels_edit', false);
            }
        },
        initData(data) {
            data = data || this;
            data.$set('tab', tab);
            data.$set('tabs', session.get('tabs', []));
            this.activate(data);
            return data;
        },
        saveTab() {
            if (!view) return;

            this.tab = tab;
            this.tabs.$set(tab, {
                url: getPath().replace(RegExp('^/[0-9]+'), ''),
                name: view.title || view.search_query
            });
            sidebar.activate();
        },
        newTab(e) {
            e.preventDefault();
            tab = this.tabs.length;
            go('/');
        },
        delTab(e) {
            e.preventDefault();
            this.tabs.$remove(e.targetVM.$index);
        },
        setFont(val) {
            $('body')[0].classList[val ? 'add' : 'remove']('bigger');
        },
        toggleFont(e) {
            e.preventDefault();
            let val = session.get('bigger') ? '' : 1;
            this.setFont(val);
            session.set('bigger', val);
        },
        search(e) {
            e.preventDefault();
            go(encodeURI('/emails/?q=' + this.search_query));
        },
        toggleHelp(e, value) {
            if(e) e.preventDefault();
            value = value !== undefined ? value : !this.show_help;
            this.$data.$set('show_help', value);
        },
        closeHelp(e) {
            this.toggleHelp(e, false);
            Mousetrap.unbind('esc');
        },
        showHelp(e) {
            this.toggleHelp(e, true);
            Mousetrap.bind('esc', (e) => this.closeHelp());
        },
        closeErrors(e) {
            this.errors = [];
        },
        focusSearch(e) {
            Mousetrap(e.target).bind('esc', (e) => {
                // TODO: check multiple fires
                Mousetrap.unbind('esc');
                this.resetSearch();
            });
        },
        showSearch(e) {
            this._search = true;
            this.labels_edit = false;
            this.$nextTick(() => $$('.search input')[0].focus());
        },
        resetSearch(e) {
            $$('.search .input--x')[0].focus();
            if (e) e.preventDefault();
            this.search_query = '';
            if (this._search) {
                this._search = false;
                this.labels_edit = true;
            }
        },
        logout(e) {
            e.preventDefault();
            send('/logout/', null, (data) => {
                user = null;
                location.href = '/login/';
            });
        },
        mark(action, name, e) {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }
            mark({action: action || '+', name: name});
        },
        archive(e) {
            this.mark('-', '\\Inbox', e);
        },
        del(e) {
            this.mark('+', '\\Trash', e);
        },
        spam(e) {
            this.mark('+', '\\Spam', e);
        },
        merge(e) {
            e.preventDefault();
            e.stopPropagation();
            newThread({
                action: 'merge',
                // FIXME: it isn't good to call view here
                ids: view.getPicked(view, (el) => el.thrid)
            }, (data) => reload());
        },
        initLabels() {
            let container = $$('.header.labels-exists')[0];
            if (!container) return;

            let vm = this;
            let tags, compl;
            let input = $$('.labels-input input');

            let save = () => {
                let new_labels = tags.value().split(',');
                mark({
                    action: '=',
                    name: new_labels,
                    old_name: vm.labels_sel
                });
                vm.labels_sel = new_labels;
                reset();
            };
            let init = () => {
                clear();
                container.classList.add('labels-input-on');

                compl = horsey(input, {suggestions: vm.labels.all});
                tags = insignia(input, {
                    deletion: true,
                    delimiter: ',',
                    parse(value) {
                        return value.trim();
                    },
                    validate(value, tags) {
                        let valid = vm.labels.all.indexOf(value) !== -1;
                        valid = valid || !value.startsWith('\\');
                        return valid && tags.indexOf(value) === -1;
                    },
                });
                input.focus();
            };
            let clear = () => {
                if (tags) tags.destroy();
                if (compl) compl.destroy();
                input.value = vm.labels_sel.join(',');
            };
            let reset = () => {
                clear();
                container.classList.remove('labels-input-on');
            };

            Mousetrap(input)
                .bind(['esc'], (e) => {
                    e.preventDefault();
                    compl.hide();
                    tags.convert();
                })
                .bind(['enter'], (e) => {
                    e.preventDefault();
                    if (compl.list.classList.contains('sey-show')) return;
                    compl.hide();
                    tags.convert();
                })
                .bind(['backspace'], (e) => {
                    if (e.target.value !== '') return;

                    // Clean previous tag
                    let prev = e.target.previousElementSibling.children;
                    if (prev.length > 0) {
                        prev[prev.length - 1].innerHTML = '';
                    }
                    tags.convert();
                })
                .bind('esc esc', (e) => reset())
                .bind('ctrl+enter', (e) => save());

            $$('.labels--edit').addEventListener('click', (e) => init());
            $$('.labels .input--ok').addEventListener('click', (e) => save());
            $$('.labels .input--x').addEventListener('click', (e) => reset());
            return reset;
        },
    }
});
let Emails = Component.extend({
    name: 'Emails',
    template: require('./emails.html'),
    ready() {
        this.$watch('emails.items', (newVal, oldVal) => {
            if (!this.thread) return;

            let ids = [];
            for (let el of this.emails.items) {
                if (el.unread) ids.push(el.vid);
            }
            if (ids.length) {
                mark({action: '-', name: '\\Unread', ids: ids}, () => {}, this);
            }
        });
    },
    directives: {
        body(value) {
            this.el.innerHTML = value;
            for (let el of $$('a', this.el)) {
                el.target = '_blank';
            }
            for (let el of $$('.email-quote-toggle', this.el)) {
                let quote = el.nextElementSibling;
                el.addEventListener('click', (e) => toggle(quote));
                toggle(quote);
            }
        },
    },
    computed: {
        last_email() {
            return this.emails.items.slice(-1)[0];
        },
    },
    methods: {
        activate() {
            if (this.replyView) this.replyView.activate();
        },
        initData(data) {
            if(!data.emails) {
                if(!data.title) data.$set('title', '');
                return data;
            }
            if (data.checked_list === undefined) {
                data.$set('checked_list', new Set());
                this.permanent('checked_list');
            }
            for (let email of data.emails.items) {
                email.vid = email[data.threads ? 'thrid' : 'id'];
                email.$set('checked', data.checked_list.has(email.vid));
            }

            if (data.has_draft) this.$nextTick(() => {
                this.initReply(this.reply_url, true);
            });
            return data;
        },
        initReply(url, focus) {
            if(!url) url = this.reply_url;

            this.$data.$set('reply_body', true);
            send(url, null, (data) => {
                let reply = $$('.compose-body')[0];
                this.replyView = new Compose({data: data, el: reply});
                if (focus) {
                    this.replyView.activate();
                }
            });
        },
        reply(e) {
            e.preventDefault();
            this.initReply(e.target.href, true);
        },
        getPicked(data, callback) {
            data = data || this;
            if (!data.emails || data.thread) return [];

            let result = [];
            for(let el of data.emails.items) {
                if (el.checked) {
                    result.push(callback ? callback(el) : el);
                }
            }
            return result;
        },
        getLabelsByPicked(data) {
            data = data || this;
            let labels = array_union(
                data.labels,
                ...this.getPicked(data, (el) => el.labels)
            );
            return labels;
        },
        pick(data, checked) {
            if (checked === undefined) checked = data.checked;
            data.checked = checked;
            if (checked){
                this.checked_list.add(data.vid);
            } else {
                this.checked_list.delete(data.vid);
            }
            //TODO: move to sidebar
            sidebar.labels_edit = this.getPicked().length > 0;
            sidebar.labels_sel = this.getLabelsByPicked();
        },
        details(e) {
            e.preventDefault();
            let body = e.targetVM.$data.body;
            body.details = !body.details;
        },
        getOrGo(e, details) {
            e.preventDefault();
            let ctx = e.targetVM;
            if (details && ctx.body.show && !ctx.body.details) {
                ctx.body.details = true;
                return;
            }
            if (ctx.body_url) {
                if (ctx.body) {
                    ctx.body.show = !ctx.body.show;
                } else {
                    ctx.body = {show: true};
                    send(ctx.body_url, null, (data) => {
                        ctx.body = data.emails.items[0].body;
                    });
                }
            } else {
                go(ctx.thread_url);
            }
        },
        pin(e) {
            let email = e.targetVM.$data,
                data = {action: '+', name: '\\Pinned', ids: [email.id]};

            if (email.pinned) {
                data.action = '-';
                if (this.$data.threads) {
                    data.ids = [email.thrid];
                    data.thread = true;
                }
            }
            email.pinned = !email.pinned;
            mark(data);
            return false;
        },
        extract(e) {
            newThread({action: 'new', ids: [e.targetVM.id]});
        },
        unreadFromHere(e) {
            e.preventDefault();

            let ids = [];
            for (let v of this.emails.items) {
                if (v.id < e.targetVM.id) {
                    continue;
                }
                ids.push(v.id);
            }
            mark({action: '+', name: '\\Unread', ids: ids}, () => {});
        },
        delete(e) {
            mark({action: '+', name: '\\Trash', ids: [e.targetVM.id]});
        },
        showSlider(e) {
            if (e.targetVM.maintype != 'image') {
                return;
            }

            e.preventDefault();
            let slides = [];
            for (let i of e.targetVM.$parent.body.attachments.items) {
                if(i.maintype == 'image') {
                    slides.push(i);
                }
            }
            new Slider({data: {slide: e.targetVM, slides: slides}});
        },
    }
});
let Compose = Component.extend({
    name: 'Compose',
    template: require('./compose.html'),
    ready() {
        let self = this;

        send(this.links.preview, this.getContext(), (data) =>
            self.$data.$set('html', data)
        );
        this.$watch('fr', this.preview);
        this.$watch('to', this.preview);
        this.$watch('subj', this.preview);
        this.$watch('body', () => this.preview(null, 3000));
        this.$watch('quoted', this.preview);
        this.$watch('files', this.preview);

        let input, compl, tags;
        input = $$('.compose-to input')[0];
        input.value = this.to;

        compl = horsey(input, {suggestions: (done) => {
            send('/search-email/?q=', null, done);
        }});
        tags = insignia(input, {
            deletion: true,
            delimiter: ',',
            parse(value) {
                return value.trim();
            },
        });
        input.addEventListener('insignia-evaluated', (e) => {
            self.to = tags.value();
        });

        Mousetrap(input)
            .bind(['esc'], (e) => {
                e.preventDefault();
                compl.hide();
                tags.convert();
            })
            .bind(['enter'], (e) => {
                e.preventDefault();
                if (compl.list.classList.contains('sey-show')) return;
                compl.hide();
                tags.convert();
            });

        this.text = $$('.compose textarea')[0];
        Mousetrap(this.text).bind('ctrl+enter', (e) => self.send());

        tabOverride.tabSize(4);
        tabOverride.set(this.text);
    },
    methods : {
        activate() {
            this.text.focus();
        },
        getContext() {
            let ctx = {};
            let fields = [
                'id', 'fr', 'to', 'subj', 'body',
                'quoted', 'forward', 'files'
            ];
            for (let f of fields) {
                ctx[f] = this[f] === undefined ? '' : this[f];
            }
            if (this.quoted) ctx.quote = this.quote;
            return ctx;
        },
        preview(e, timeout) {
            if (timeout && this.last && new Date() - this.last < timeout) {
                this.once = this.preview;
                setTimeout(() => this.once && this.once(), timeout / 2);
                return;
            }
            this.once = null;
            this.last = new Date();

            let self = this;
            send(this.links.preview + '?save=1', this.getContext(), (data) => {
                self.$data.$set('html', data);
                self.$data.$set('draft', true);
            });
        },
        clear(e) {
            send(this.links.rm, null, (data) => {
                view = null;
                reload();
            });
        },
        upload(e) {
            let self = this;
            let input = e.target;
            let data = new FormData();
            data.append('count', this.files.length);
            for (let file of Array.from(input.files)) {
                data.append('files', file, file.name);
            }
            api(this.links.upload, {method: 'post', body: data})
                .then((data) => {
                    self.files = self.files.concat(data);
                    input.value = null;
                });
        },
        send(e) {
            if (e) e.preventDefault();
            this.$data.$set('hide', true);
            send(this.links.send, this.getContext(), {
                success: (data => go(data.url)),
                error: (err => {
                    error(err);
                    this.$data.hide = false;
                })
            });
        }
    }
});

/* Related functions */
function $(selector, root) {
    root = root || document;
    let elements = Array.from(root.querySelectorAll(selector));
    return elements;
}
function $$(selector, root) {
    return $(selector, root || $('.body-active')[0]);
}
function toggle(el, state) {
    if (state === undefined) {
        state = el.style.display == 'none';
    }
    el.style.display = state ? '' : 'none';
}
function escapeQuery(v) {
    return v.indexOf(' ') == -1 ? v : '"' + v + '"';
}
function goToLabel(label) {
    go('/emails/?q=in:' + escapeQuery(label));
}
function filterEmails(condition) {
    if (view.constructor != Emails || view.thread) return;

    let items = [];
    for (let item of view.emails.items) {
        if (condition(item)) {
            items.push(item);
        }
    }
    return items;
}
function getPath() {
    return location.pathname + location.search;
}
function go(url) {
    url = url.replace(location.origin, '');
    if (!RegExp('^/[0-9]+/').test(url)) {
        url = `/${tab}${url}`;
    }
    return history.pushState({}, url);
}
function reload() {
    return history.replaceState({}, getPath());
}

function newThread(params, callback) {
    callback = callback || (data => go(data.url));
    send('/thread/new/', params, callback);
}
function debug(...items) {
    if (conf.debug) console.log(...items);
}
function error(err) {
    console.log(err);
    if (sidebar) sidebar.errors.push(err);
}
function mark(params, callback, emails) {
    view = emails || view;
    if (view.constructor != Emails) return;

    if (!params.ids) {
        if (view.$data.thread) {
            params.ids = [view.$data.emails.items[0].thrid];
            params.thread = true;
        } else {
            params.thread = view.$data.threads;
            params.ids = view.getPicked(view, (el) => el.vid);
        }
    }
    if (params.thread) {
        params.last = view.$data.emails.last;
    }
    callback = callback || ((data) => reload());
    send('/mark/', params, callback);
}
function connect() {
    ws = new WebSocket(conf.host_ws);
    ws.onopen = () => {
        console.log('ws opened');
        wsTry = 0;
    };
    ws.onerror = (error) => {
        console.log('ws error', error);
    };
    ws.onmessage = (e) => {
        let data = JSON.parse(e.data);
        if (data.uid !== undefined) {
            let handler = handlers[data.uid];
            if (handler) {
                let elapsed = (Date.now() - handler.time) / 1000;
                console.log(`response for ${data.uid} (${elapsed}s)`);

                parseJson(data.payload)
                    .then(handler.callback.success)
                    .catch(handler.callback.error || (ex => {
                        error([data.uid, ex]);
                    }));
                delete handlers[data.uid];
            } else {
                console.warn(`No handler for ${data.uid}`);
            }
        } else if (data.session) {
            document.cookie = data.session;
        } else if (data.notify) {
            if (data.ids.length) {
                console.log(`Notify: ${data.ids.length} updated`);
                sidebar.fetch();
            }
            if (data.last_sync) {
                send('/info/', null, (data) => {
                    debug(`Notify: last sync at ${data.last_sync}`);
                    sidebar.last_sync = data.last_sync;
                });
            }
        }
    };
    ws.onclose = (event) => {
        ws = null;
        console.log('ws closed', event);
        setTimeout(connect, conf.ws_timeout * (Math.pow(2, wsTry) - 1));
        wsTry++;
    };
}
function api(url, params, data) {
    url = '/api' + url.replace(location.origin, '');

    params = params || {};
    params.credentials = 'same-origin';
    params.method = params.method || 'get';
    params.headers = Object.assign(params.headers || {}, {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json'
    });
    if (data) {
        params.headers['Content-Type'] = 'application/json';
        params.body = JSON.stringify(data);
    }
    return fetch(url, params)
        .then(r => {
            if (r.status == 200) {
                return r;
            } else if (r.status == 403) {
                location.href = '/login/';
                throw 'Redirect to login';
            } else {
                throw `${r.status} ${r.statusText}`;
            }
        })
        .then(r => r.text())
        .then(parseJson);
}
function parseJson(data) {
    return new Promise((resolve, reject) => {
        try {
            return resolve(JSON.parse(data));
        } catch(error) {
            reject(error);
        }
    });
}
function send(url, data, callback) {
    url = url.replace(location.origin, '');
    if (tab !== undefined) {
        url = url.replace(RegExp('^/' + tab), '');
    }
    callback = {
        success: callback && callback.success || callback,
        error: callback && callback.error || (
            !conf.debug ? (ex => error([url, ex])) : null
        )
    };

    if (ws && conf.ws_proxy && ws.readyState === ws.OPEN) {
        data = {
            url: url,
            payload: data,
            uid: handlerSeq++,
            cookie: document.cookie
        };
        console.log(url, data.uid);
        ws.send(JSON.stringify(data));
        if (callback) {
            handlers[data.uid] = {
                callback: callback,
                time: Date.now(),
                url: url
            };
        }
    } else {
        let params = {
            method: data ? 'POST': 'GET',
            headers: {}
        };
        api(url, params, data).then(callback.success).catch(callback.error);
    }
}
