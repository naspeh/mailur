import Vue from 'vue';
import createHistory from 'history/lib/createBrowserHistory';

require('es6-promise').polyfill();
require('whatwg-fetch');
Vue.config.debug = conf.debug;

let ws, ws_try = 0, handlers = {};
if (conf.ws_enabled) {
    connect();
}

let history = createHistory();
history.listen((location) => {
    let path = location.pathname + location.search;
    send(path, null, function(data) {
        if (!data._name) {
            document.querySelector('.body').innerHTML = data;
        } else {
            views[data._name].$data = data;
        }
    });
});

let Component = Vue.extend({
    replace: false,
    proto: false,
    silent: true,
    mixins: [{
        methods: {
            fetch() {
                let self = this;
                send(this.url, null, (data) => {
                    self.$data = data;
                });
            },
            go(e, url) {
                if(e) e.preventDefault();
                url = url ? url : e.target.href;
                go(url);
            },
        },
    }]
});
let emails = new Component({
    el: '.emails.body',
    template: require('./emails.html'),
    data: {},
    methods: {
        details: function(e) {
            if(e) e.preventDefault();
            let body = e.targetVM.$data.body;
            body.details = !body.details;
        },
        getOrGo: function(url, ctx) {
            if (this.$data.thread) {
                if (ctx.body) {
                    ctx.body.show = !ctx.body.show;
                } else {
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
});
let sidebar = new Component({
    replace: true,
    el: '.sidebar',
    template: require('./sidebar.html'),
    data: {},
    created() {
        this.url = '/sidebar/';
        this.fetch();
    },
    methods: {
        submit: function(e) {
            e.preventDefault();
            go('/search/?q=' + this.$data.search_query);
        }
    }
});
let compose = new Component({
    el: '.compose.body',
    template: require('./compose.html'),
    data: {},
    created() {
        this.url = '/compose/';
        this.fetch();
    }
});
let views = {
    emails: emails,
    sidebar: sidebar,
    compose: compose
};

/* Related functions */
function go(url) {
    return history.pushState({}, url.replace(location.origin, ''));
}
function reload() {
    return history.replaceState({}, location.pathname + location.search);
}
function mark(params, callback) {
    if (params.thread) {
        params.last = emails.$data.emails.last;
    }

    // if (!params.ids) {
    //     if ($('.emails').hasClass('thread')) {
    //         params.ids = [$('.email').first().data('thrid')];
    //         params.thread = true;
    //     } else {
    //         var field = is_thread ? 'thrid' : 'id';
    //         params.thread = field == 'thrid';
    //         params.ids = getSelected(field);
    //     }
    // }
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
            if (emails.$data.threads) {
                reload();
            }
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
