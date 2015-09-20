import * as utils from './app_utils';
import Vue from 'vue';
import createHistory from 'history/lib/createBrowserHistory';
import Mousetrap from 'mousetrap';
import insignia from 'insignia';
import horsey from 'horsey';

Vue.config.debug = conf.debug;
Vue.config.proto = false;

let ws, ws_try = 0, handlers = {};
if (conf.ws_enabled) {
    connect();
}

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
    [['r r'], 'Reply', () => view.tread && go(view.last_email.links.reply)],
    [['r r'], 'Reply all',
        () => view.thread && go(view.last_email.links.replyall)
    ],
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
    if (!this.$parent) {
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
        search(e) {
            e.preventDefault();
            go(encodeURI('/search/?q=' + this.$data.search_query));
        },
        toggleHelp(e, value) {
            if(e) e.preventDefault();
            value = value !== undefined ? value : !this.$data.show_help;
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
        this.$watch('thread', (newVal, oldVal) => {
            if (!newVal) return;

            let ids = [];
            for (let el of this.emails.items) {
                if (el.unread) ids.push(el.vid);
            }
            if (ids.length) {
                mark({action: '-', name: '\\Unread', ids: ids}, () => {}, this);
            }
        });
        this.$watch('checked_list', (newVal, oldVal) => {
            this.refreshLabels();
        });
    },
    directives: {
        body(value) {
            this.el.innerHTML = value;
            for (let el of this.el.querySelectorAll('a')) {
                el.target = '_blank';
            }
            for (let el of this.el.querySelectorAll('.email-quote-toggle')) {
                let quote = el.nextElementSibling;
                el.addEventListener('click', (e) => toggle(quote));
                toggle(quote);
            }
        },
    },
    elementDirectives: {
        // FIXME: should be a better way
        labels: {bind() {
            this.vm.refreshLabels();
        }}
    },
    computed: {
        last_email() {
            return this.emails.items.slice(-1)[0];
        }
    },
    methods: {
        initData(data) {
            if (data.checked_list === undefined) {
                data.$set('checked_list', new Set());
                this.permanent('checked_list');
            }
            for (let email of data.emails.items) {
                email.vid = email[data.threads ? 'thrid' : 'id'];
                email.$set('checked', this.checked_list.has(email.vid));
            }

            data.$set('labels_edit',
                this.getPicked(data).length > 0 || data.thread ? true : false
            );
            data.$set('labels',  this.getLabelsByPicked(data));
            return data;
        },
        refreshLabels() {
            let container = $('.header .labels')[0];
            if (!container) return;

            let vm = this;
            let $$ = container.querySelector.bind(container);
            let labels = $$('.labels-edit');

            let tags, compl;
            let edit = $$('.labels-input');
            toggle(edit);

            let save = () => {
                vm.labels = tags.value().split(',');
                compl.destroy();
                tags.destroy();

                mark({
                    action: '=',
                    name: vm.labels,
                    old_name: this.getLabelsByPicked(this)
                });
                toggle(labels);
                toggle(edit);
            };
            let init = () => {
                reset();
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
                toggle(labels);
                toggle(edit);
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
                .bind('esc esc', (e) => reset())
                .bind('ctrl+enter', (e) => save());

            $$('.labels--ok').addEventListener('click', (e) => save());
            $$('.labels--cancel').addEventListener('click', (e) => reset());
            $$('.labels--edit').addEventListener('click', (e) => init());
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
            let labels = utils.array_union(
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
            send('/new-thread/', params, (data) => go(data.url));
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
    created() {
        this.preview();
        this.$watch('body', () => this.preview(null, 3000));
        this.$watch('quoted', this.preview);
    },
    methods : {
        getContext() {
            let ctx = {};
            for (let f of ['fr', 'to', 'subj', 'body', 'quoted']) {
                ctx[f] = this[f] === undefined ? '' : this[f];
            }
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

            let params = {
                target: getPath(),
                context: this.getContext(),
            };
            if (this.quoted) params.quote = this.quote;

            let self = this;
            fetchRaw('/preview/', params, (data) => {
                self.$data.$set('html', data);
            });
        },
    }
});

let views = {
    emails: Emails,
    compose: Compose
};
let view;
let base_title = document.title;
let history = createHistory();
history.listen((location) => {
    send(getPath(), null, (data) => {
        let current = views[data._name];
        if (!view || view.name() != data._name) {
            view = new current({data: data, el: '.body'});
        } else {
            view.$data = data;
        }
        document.title = `${data.header.title} - ${base_title}`;
    });
});


/* Related functions */
function $(selector, callback) {
    let elements = Array.from(document.querySelectorAll(selector));
    let results = [];
    if (callback) {
        for (let el of elements) {
            results.push(callback(el));
        }
        elements = results;
    }
    return elements;
}
function toggle(el) {
    el.style.display = el.style.display == 'none' ? '' : 'none';
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
        ws_try = 0;
    };
    ws.onerror = (error) => {
        console.log('ws error', error);
    };
    ws.onmessage = (e) => {
        let data = JSON.parse(e.data);
        if (data.uid) {
            console.log('response for ' + data.uid);
            let handler = handlers[data.uid];
            if (handler) {
                handler(JSON.parse(data.payload));
                delete handlers[data.uid];
            }
        } else if (data.updated) {
            console.log(data);
            sidebar.fetch();
            if (view.name() == 'emails' && view.$data.threads) reload();
        }
    };
    ws.onclose = (event) => {
        ws = null;
        console.log('ws closed', event);
        setTimeout(connect, conf.ws_timeout * Math.pow(2, ws_try));
        ws_try++;
    };
}
function fetchRaw(url, data, callback) {
    let params = {
        credentials: 'same-origin',
        method: data ? 'POST': 'GET',
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json',
        },
    };
    if (data) {
        params.headers['Content-Type'] = 'application/json';
        params.body = JSON.stringify(data);
    }
    fetch(url, params)
        .then(r => r.json())
        .then(callback)
        .catch(ex => console.log(url, ex));
}
function send(url, data, callback) {
    console.log(url);
    if (ws && ws.readyState === ws.OPEN) {
        url = conf.host_web.replace(/\/$/, '') + url;
        data = {url: url, payload: data, uid: utils.guid()};
        ws.send(JSON.stringify(data));
        if (callback) {
            handlers[data.uid] = callback;
        }
    } else {
        fetchRaw(url, data, callback);
    }
}
