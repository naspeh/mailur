import Vue from 'vue';
import createHistory from 'history/lib/createBrowserHistory';
import Mousetrap from 'mousetrap';

require('es6-promise').polyfill();
require('whatwg-fetch');
Vue.config.debug = conf.debug;
Vue.config.proto = false;

let ws, ws_try = 0, handlers = {};
if (conf.ws_enabled) {
    connect();
}

/* Keyboard shortcuts */
let hotkeys = [
    [['s a', '* a'], 'Select all conversations',
        () => $('.email .email-pick input', (el) => el.checked = true)
    ],
    [['s n', '* n'], 'Deselect all conversations',
        () => $('.email .email-pick input', (el) => el.checked = false)
    ],
    [['s r', '* r'], 'Select read conversations',
        () => $('.email:not(.email-unread) .email-pick input', (el) =>
            el.checked = true
        )
    ],
    [['s u', '* u'], 'Select unread conversations',
        () => $('.email.email-unread .email-pick input', (el) =>
            el.checked = true
        )
    ],
    [['s p', '* s'], 'Select pinned conversations',
        () => $('.email.email-pinned .email-pick input', (el) =>
            el.checked = true
        )
    ],
    [['s shift+p', '* t'], 'Select unpinned conversations',
        () => $('.email:not(.email-pinned) .email-pick input', (el) =>
            el.checked = true
        )
    ],
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
    [['m l'], 'Edit labels', () => $('.email-labels-edit input')[0].focus()],
    [['r r'], 'Reply', () => go(getLastEmail().links.reply)],
    [['r a'], 'Reply all', () => go(getLastEmail().links.replyall)],
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
            _fetch() {
                let self = this;
                send(this.url, null, (data) => {
                    self.$data = data;
                });
            },
            fetch() {
                this._fetch();
            },
            name() {
                return this.$data._name;
            },
            go(e, url) {
                if(e) e.preventDefault();
                url = url ? url : e.target.href;
                go(url);
            },
        },
    }],
});
let sidebar = new Component({
    replace: true,
    el: '.sidebar',
    template: require('./sidebar.html'),
    data: {},
    created() {
        this.url = '/sidebar/';
        this.fetch();
        this.help = '';
        for (let item of hotkeys) {
            Mousetrap.bind(item[0], item[2].bind(this), 'keyup');
            this.help += `<div><b>${item[0][0]}</b>: ${item[1]}</div>`;
        }
    },
    methods: {
        submit: function(e) {
            e.preventDefault();
            go('/search/?q=' + this.$data.search_query);
        },
        toggleHelp: function(e, value) {
            if(e) e.preventDefault();
            value = value !== undefined ? value : !this.$data.show_help;
            this.$data.$set('show_help', value);
        },
        closeHelp: function(e) {
            this.toggleHelp(e, false);
        },
        showHelp: function(e) {
            this.toggleHelp(e, true);
        },
    }
});
let emails = (data) => {return new Component({
    el: '.body',
    template: require('./emails.html'),
    data: data,
    created() {
        for (let i of this.$data.emails.items) {
            i.checked = false;
        }
    },
    methods: {
        details: function(e) {
            if(e) e.preventDefault();
            let body = e.targetVM.$data.body;
            body.details = !body.details;
        },
        getOrGo: function(url, ctx, e) {
            e.preventDefault();
            if (this.$data.thread) {
                if (ctx.body) {
                    ctx.body.show = !ctx.body.show;
                } else {
                    ctx.body = {show: true};
                    send(url, null, (data) => {
                        ctx.body = data.emails.items[0].body;
                    });
                }
            } else {
                go(url);
            }
            return false;
        },
        pin: function(e) {
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
        quotes: function(e) {
            if (e.target.className == 'email-quote-toggle') {
                let q = e.target.nextSibling;
                q.style.display = q.style.display == 'block' ? 'none' : 'block';
            }
        }
    }
});};
let compose = (data) => {return new Component({
    el: '.body',
    template: require('./compose.html'),
    data: data,
});};

let views = {
    emails: emails,
    compose: compose
};
let view;
let base_title = document.title;
let history = createHistory();
history.listen((location) => {
    let path = location.pathname + location.search;
    send(path, null, function(data) {
        let current = views[data._name];
        if (!view || view.name() != data._name) {
            view = current(data);
        }
        view.$data = data;
        document.title = `${data.header.title} - ${base_title}`;
    });
});


/* Related functions */
function $(selector, callback) {
    let elements = Array.from(document.querySelectorAll(selector));
    if (callback) {
        for (let el of elements) {
            callback(el);
        }
    }
    return elements;
}
function getLastEmail() {
    if (view.name() != 'emails') return;
    return view.$data.slice(-1)[0];
}
function goToLabel(label) {
    go('/emails/?in=' + label);
}
function go(url) {
    return history.pushState({}, url.replace(location.origin, ''));
}
function reload() {
    return history.replaceState({}, location.pathname + location.search);
}
function mark(params, callback) {
    if (view.name() != 'emails') return;

    if (!params.ids) {
        if (view.$data.thread) {
            params.ids = [view.$data.emails.items[0].thrid];
            params.thread = true;
        } else {
            var field =  view.$data.threads ? 'thrid' : 'id';
            params.thread = field == 'thrid';
            params.ids = [];
            for (let i of view.$data.emails.items) {
                if (i.checked) params.ids.push(i[field]);
            }
        }
    }
    if (params.thread) {
        params.last = view.$data.emails.last;
    }
    callback = callback || ((data) => {});
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
            let checked = $('.email-pick input:checked').length;
            let threads = view.name() == 'emails' && view.$data.threads;
            if (threads && !checked) reload();
        }
    };
    ws.onclose = (event) => {
        ws = null;
        console.log('ws closed', event);
        setTimeout(connect, conf.ws_timeout * Math.pow(2, ws_try));
        ws_try++;
    };
}
// Ref: http://stackoverflow.com/questions/105034/create-guid-uuid-in-javascript
function guid() {
    var d = new Date().getTime();
    var uuid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(
        /[xy]/g,
        (c) => {
            var r = (d + Math.random() * 16) % 16 | 0;
            d = Math.floor(d / 16);
            return (c == 'x' ? r : (r & 0x3 | 0x8)).toString(16);
        });
    return uuid;
}
function send(url, data, callback) {
    console.log(url);
    if (ws && ws.readyState === ws.OPEN) {
        url = conf.host_web.replace(/\/$/, '') + url;
        data = {url: url, payload: data, uid: guid()};
        ws.send(JSON.stringify(data));
        if (callback) {
            handlers[data.uid] = callback;
        }
    } else {
        fetch(url, {
            credentials: 'same-origin',
            method: data ? 'POST': 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            body: data && JSON.stringify(data)
        })
            .then(r => r.json())
            .then(callback)
            .catch(ex => console.log(url, ex));
    }
}
