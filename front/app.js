import * as polyfills from './polyfills';
import Mousetrap from 'mousetrap';
import Vue from 'vue';
import createHistory from 'history/lib/createBrowserHistory';
import horsey from 'horsey';
import insignia from 'insignia';

Vue.config.debug = conf.debug;
Vue.config.proto = false;

let array_union = require('lodash/array/union');
let ws, wsTry = 0, handlers = {}, handlerSeq = 0;
let view, history, title = document.title;
send('/check-auth/', null, (data) => {
    if (!data.username) {
        location.pathname = '/api/login/';
        return;
    }
    if (conf.ws_enabled) {
        connect();
    }
    history = createHistory();
    history.listen((location) => {
        if (location.pathname == '/') {
            return go('/emails/?in=\\Inbox');
        }
        send(getPath(), null, (data) => {
            let current = views[data._name];
            if (!view || view.name() != data._name) {
                view = new current({data: data, el: '.body'});
            } else {
                view.$data = data;
            }
            if (data.header) {
                document.title = `${data.header.title} - ${title}`;
            }
        });
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
            name() {
                return this.$data._name;
            },
            fetch(callback) {
                let self = this;
                send(this.url, null, (data) => {
                    self.$data = data;
                    if (callback) callback(data);
                });
            },
            go(e, url) {
                if(e) e.preventDefault();
                url = url ? url : e.target.href;
                go(url);
            },
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

let sidebar = new Component({
    replace: true,
    template: require('./sidebar.html'),
    created() {
        this.url = '/sidebar/';
        this.fetch((data) => this.$mount('.sidebar'));

        this.help = '';
        for (let item of hotkeys) {
            Mousetrap.bind(item[0], item[2].bind(this), 'keyup');
            this.help += `<div><b>${item[0][0]}</b>: ${item[1]}</div>`;
        }
    },
    methods: {
        initData(data) {
            data.$set('search_query', '');
            return data;
        },
        search(e) {
            e.preventDefault();
            go(encodeURI('/search/?q=' + this.search_query));
        },
        toggleHelp(e, value) {
            if(e) e.preventDefault();
            value = value !== undefined ? value : !this.show_help;
            this.$data.$set('show_help', value);
        },
        closeHelp(e) {
            this.toggleHelp(e, false);
        },
        showHelp(e) {
            this.toggleHelp(e, true);
        },
    }
});
let Emails = Component.extend({
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
        this.$watch('labels', () => this.$nextTick(this.resetLabels));
    },
    directives: {
        body(value) {
            this.el.innerHTML = value;
            for (let el of $('a', this.el)) {
                el.target = '_blank';
            }
            for (let el of $('.email-quote-toggle', this.el)) {
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
        initData(data) {
            sidebar.search_query = data.search_query || '';

            if(!data.emails) {
                // TODO: maybe should update template instead of filling
                data.$set('labels', []);
                if(!data.header) data.$set('header', {title: '', buttons: []});
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

            data.$set('labels_edit',
                this.getPicked(data).length > 0 || data.thread ? true : false
            );
            data.$set('labels',  this.getLabelsByPicked(data));

            this.$nextTick(() => {
                if (this.resetLabels === undefined) {
                    this.resetLabels = this.initLabels();
                }
                this.resetLabels();
            });
            return data;
        },
        initReply(url, focus) {
            if(!url) return;

            this.$data.$set('reply_body', true);
            send(url, null, (data) => {
                let reply = $('.compose-body')[0];
                new Compose({data: data, el: reply});
                if (focus) {
                    setTimeout(() => reply.scrollIntoView(true), 500);
                }
            });
        },
        reply(e) {
            e.preventDefault();
            this.initReply(e.target.href, true);
        },
        initLabels() {
            let container = $('.header .labels')[0];
            if (!container) return;

            let vm = this;
            let $$ = container.querySelector.bind(container);
            let labels = $$('.labels-edit');

            let tags, compl;
            let edit = $$('.labels-input');

            let save = () => {
                vm.labels = tags.value().split(',');
                mark({
                    action: '=',
                    name: vm.labels,
                    old_name: this.getLabelsByPicked(this)
                });
                reset();
            };
            let init = () => {
                clear();
                toggle(edit, true);
                toggle(labels, false);

                compl = horsey(input, {suggestions: vm.header.labels.all});
                tags = insignia(input, {
                    deletion: true,
                    delimiter: ',',
                    parse(value) {
                        return value.trim();
                    },
                    validate(value, tags) {
                        let valid = vm.header.labels.all.indexOf(value) !== -1;
                        valid = valid || !value.startsWith('\\');
                        return valid && tags.indexOf(value) === -1;
                    },
                });
                input.focus();
            };
            let clear = () => {
                if (tags) tags.destroy();
                if (compl) compl.destroy();
                input.value = vm.labels.join(',');
            };
            let reset = () => {
                clear();
                toggle(labels, true);
                toggle(edit, false);
            };
            let input = edit.querySelector('input');

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

            $$('.labels--ok').addEventListener('click', (e) => save());
            $$('.labels--cancel').addEventListener('click', (e) => reset());
            $$('.labels--edit').addEventListener('click', (e) => init());
            return reset;
        },
        getLabels(names) {
            let result = [];
            for (let i of names) {
                result.push({name: i, url: this.header.labels.base_url + i});
            }
            return result;
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
                data.header.labels.items,
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
            this.labels_edit = this.getPicked().length > 0;
            this.labels = this.getLabelsByPicked();
        },
        details(e) {
            if(e) e.preventDefault();
            let body = e.targetVM.$data.body;
            body.details = !body.details;
        },
        getOrGo(e) {
            e.preventDefault();
            let ctx = e.targetVM;
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
            return false;
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
        mark(action, name, e) {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }

            // FIXME
            if (!name) return this.merge();

            mark({action: action || '+', name: name});
        },
        newThread(params) {
            send('/thread/new/', params, (data) => go(data.url));
        },
        merge(e) {
            this.newThread({
                action: 'merge',
                ids: this.getPicked(this, (el) => el.thrid)
            });
        },
        extract(e) {
            this.newThread({action: 'new', ids: [e.targetVM.id]});
        },
        delete(e) {
            mark({action: '+', name: '\\Trash', ids: [e.targetVM.id]});
        },
    },
});
let Compose = Component.extend({
    template: require('./compose.html'),
    ready() {
        let self = this;

        send(this.previewUrl(), this.getContext(), (data) =>
            self.$data.$set('html', data)
        );
        this.$watch('fr', this.preview);
        this.$watch('to', this.preview);
        this.$watch('subj', this.preview);
        this.$watch('body', () => this.preview(null, 3000));
        this.$watch('quoted', this.preview);
        this.$watch('files', this.preview);

        let input, compl, tags;
        input = $('.compose-to input')[0];
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

        let text = $('.compose textarea')[0];
        Mousetrap(text).bind('ctrl+enter', (e) => self.send());
    },
    methods : {
        getContext() {
            let ctx = {};
            let fields = [
                'id', 'target', 'fr', 'to', 'subj', 'body',
                'quoted', 'forward', 'files'
            ];
            for (let f of fields) {
                ctx[f] = this[f] === undefined ? '' : this[f];
            }
            if (this.quoted) ctx.quote = this.quote;
            return ctx;
        },
        previewUrl(save) {
            save = save || '';
            return `/draft/preview/${this.target}/?save=${save}`;
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
            send(this.previewUrl(true), this.getContext(), (data) => {
                self.$data.$set('html', data);
                self.$data.$set('draft', true);
            });
        },
        clear(e) {
            send(`/draft/rm/${this.target}/`, null, (data) => {
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
            ajax(`/draft/upload/${this.target}/`, {method: 'post', body: data})
                .then((data) => {
                    self.files = self.files.concat(data);
                    input.value = null;
                });
        },
        send(e) {
            if (e) e.preventDefault();
            this.$data.$set('hide', true);
            send(`/draft/send/${this.target}/`, this.getContext(), (data) => {
                go(data.url);
            });
        }
    }
});

let views = {
    emails: Emails,
    compose: Compose
};

/* Related functions */
function $(selector, root) {
    root = root || document;
    let elements = Array.from(root.querySelectorAll(selector));
    return elements;
}
function toggle(el, state) {
    if (state === undefined) {
        state = el.style.display == 'none';
    }
    el.style.display = state ? '' : 'none';
}
function goToLabel(label) {
    go('/emails/?in=' + label);
}
function filterEmails(condition) {
    if (view.name() != 'emails' || view.thread) return;

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
    return history.pushState({}, url.replace(location.origin, ''));
}
function reload() {
    return history.replaceState({}, getPath());
}
function mark(params, callback, emails) {
    view = emails || view;
    if (view.name() != 'emails') return;

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
                        console.log(data.uid, ex);
                    }));
                delete handlers[data.uid];
            } else {
                console.warn(`No handler for ${data.uid}`);
            }
        } else if (data.session) {
            document.cookie = data.session;
        } else if (data.updated) {
            console.log(data);
            sidebar.fetch();
            if (view.name() == 'emails' && view.$data.threads) reload();
        }
    };
    ws.onclose = (event) => {
        ws = null;
        console.log('ws closed', event);
        setTimeout(connect, conf.ws_timeout * (Math.pow(2, wsTry) - 1));
        wsTry++;
    };
}
function ajax(url, params) {
    params.credentials = 'same-origin';
    params.headers = Object.assign(params.headers || {}, {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json'
    });
    return fetch(url, params)
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
    callback = {
        success: callback && callback.success || callback,
        error: callback && callback.error || (ex => console.log(url, ex))
    };

    if (ws && ws.readyState === ws.OPEN) {
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
        if (data) {
            params.headers['Content-Type'] = 'application/json';
            params.body = JSON.stringify(data);
        }
        ajax('/api' + url, params).then(callback.success).catch(callback.error);
    }
}
