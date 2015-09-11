import Ractive from 'ractive/ractive.runtime';
import createHistory from 'history/lib/createBrowserHistory';

let ws, ws_try = 0, handlers = {};
if (conf.use_ws) {
    connect();
}

let history = createHistory();
history.listen((location) => {
    let path = location.pathname + location.search;
    send(path, null, function(data) {
        if (!data._name) {
            document.querySelector('.body').innerHTML = data;
        } else {
            views[data._name].set(data);
        }
    });
});
let Component = Ractive.extend({
    twoway: false,
    modifyArrays: false,
    onrender() {
        this.on('go', (event) => {
            go(event.context.url || event.node.href);
            return false;
        });
    },
    fetch() {
        let self = this;
        send(this.url, null, (data) => {
            self.set(data);
        });
    },
});

let emails = new Component({
    el: '.emails.body',
    template: require('./emails.mustache'),
    data: {},
    decorators: {
        'quotes': (node) => {
            let quotes = node.querySelectorAll('.email-quote-toggle');
            for (let t of Array.from(quotes)) {
                t.addEventListener('click', (event) => {
                    let q = event.target.nextSibling;
                    q.style.display = q.style.display == 'block' ? 'none' : 'block';
                });
            }
            return {teardown: () => {}};
        }
    }
});
emails.on({
    'get-or-go': function(event) {
        let url = event.context.url;
        if (this.get('thread')) {
            if (event.context.body) {
                this.toggle(event.keypath + '.body.show');
            } else {
                send(url, null, (data) => {
                    this.set(event.keypath + '.body', data.emails.items[0].body);
                });
            }
        } else {
            go(url);
        }
        return false;
    },
    'details': function(event) {
        this.toggle(event.keypath + '.details');
        return false;
    },
    'pin': function(event) {
        let email = event.context,
            data = {action: '+', name: '\\Pinned', ids: [email.id]};

        if (email.pinned) {
            data.action = '-';
            if (this.get('threads')) {
                data.ids = [email.thrid];
                data.thread = true;
            }
        }
        this.toggle(event.keypath + '.pinned');
        mark(data);
        return false;
    }
});

let sidebar = new Component({
    el: '.sidebar',
    template: require('./sidebar.mustache'),
    data: {},
    oninit() {
        this.url = '/sidebar/';
        this.fetch();
    }
});

let compose = new Component({
    // el: '.compose.body',
    template: require('./compose.mustache'),
    data: {},
    oninit() {
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
        params.last = emails.get('emails.last');
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
            if (emails.get('threads')) {
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
    url += (url.indexOf('?') === -1 ? '?' : '&') + 'fmt=json';
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
