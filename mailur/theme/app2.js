import Ractive from 'ractive/ractive.runtime';
import createHistory from 'history/lib/createBrowserHistory';

let ws, handlers = {};
if (conf.use_ws) {
    connect();
}

let history = createHistory();
history.listen(function(location) {
    let path = location.pathname + location.search;
    console.log(path);
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
    go(url) {
        history.pushState({}, url.replace(location.origin, ''));
        return false;
    },
    ongo(event) {
        this.go(event.context.url || event.node.href);
        return false;
    },
    onrender() {
        this.on('go', this.ongo);
    },
    fetch() {
        let self = this;
        send(this.url, null, function(data) {
            self.set(data);
        });
    }
});

let emails = new Component({
    el: '.emails.body',
    template: require('./emails.mustache'),
    data: {},
    ongo(event) {
        let url = event.context.url;
        if (this.get('thread')) {
            if (event.context.body) {
                event.context.body.show = !event.context.body.show;
                this.set(event.keypath, event.context);
            } else {
                send(url, null, (function(data) {
                    this.set(event.keypath + '.body', data.emails.items[0].body);
                }).bind(this));
            }
        } else {
            this.go(url);
        }
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
function connect() {
    ws = new WebSocket(conf.host_ws);
    ws.onopen = function() {
        console.log('ws opened');
    };
    ws.onerror = function(error) {
        console.log('ws error', error);
    };
    ws.onmessage = function(e) {
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
            history.replaceState({}, location.pathname + location.search);
        }
    };
    ws.onclose = function(event) {
        ws = null;
        console.log('ws closed', event);
        setTimeout(connect, 10000);
    };
}
// Ref: http://stackoverflow.com/questions/105034/create-guid-uuid-in-javascript
function guid() {
    var d = new Date().getTime();
    var uuid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(
        /[xy]/g,
        function(c) {
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
        url = conf.host_web + url;
        var resp = {url: url, payload: data, uid: guid()};
        ws.send(JSON.stringify(resp));
        if (callback) {
            handlers[resp.uid] = callback;
        }
    } else {
        fetch(url, {
            credentials: 'same-origin',
            method: data ? 'POST': 'GET',
            body: data
        }).then(r => r.json()).then(callback);
    }
}
