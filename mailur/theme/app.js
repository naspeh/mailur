var ws = null, handlers = {}, messages = [];

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
function connect() {
    ws = new WebSocket('ws://localhost:5001');
    ws.onopen = function() {
        console.log('ws opened');
        while (messages.length > 0) {
            messages.pop()();
        }
    };
    ws.onerror = function(error) {
        console.log('ws error', error);
    };
    ws.onmessage = function(e) {
        data = JSON.parse(e.data);
        if (data.uid) {
            console.log('response for ' + data.uid);
            var handler = handlers[data.uid];
            if (handler) {
                handler(data.payload);
                delete handlers[data.uid];
            }
        } else if (data.updated) {
            console.log(data);
            var path = location.pathname + location.search;
            send(path, null, function(data) {
                if (path.search('^/thread/') != -1) {
                    updateEmails(data, true);
                } else if (path.search('^/emails/') != -1) {
                    updateEmails(data);
                } else {
                    $('body').html(data);
                }
            });
        }
    };
    ws.onclose = function(event) {
        ws = null;
        console.log('ws closed', event);
        setTimeout(connect, 10000);
    };
}
function send(url, data, callback) {
    if (ws && ws.readyState === ws.OPEN) {
        url = 'http://localhost:5000' + url;
        var resp = {url: url, payload: data, uid: guid()};
        ws.send(JSON.stringify(resp));
        if (callback) {
            handlers[resp.uid] = callback;
        }
    } else {
        messages = [function() {send(url, data, callback);}].concat(messages);
    }
}
function updateEmails(data, thread) {
    var container = $('.emails');
    $(data).find('.email').each(function() {
        var $this = $(this);
        var exists = $('#' + $this.attr('id'));
        if (exists.length && $this.data('hash') != exists.data('hash')) {
            exists.replaceWith(this);
        } else if (!exists.length) {
            if (thread) {
                container.append(this);
            } else {
                container.prepend(this);
            }
        }
    });
}

connect();
$('.emails-byid').on('click', '.email-info', function() {
    var email = $(this).parents('.email');
    email.toggleClass('email-show');
    if (email.hasClass('email-show') && !email.hasClass('email-showed')) {
        send(email.data('body-url'), null, function(data) {
            email.find('.email-body').replaceWith(
                $(data).find('#' + email.attr('id') + ' .email-body')
            );
        });
    }
    return false;
});
$('.emails').on('click', ' .email-details-toggle', function() {
    $(this).parents('.email').find('.email-details').toggle();
    return false;
});
$('.emails').on('click', '.email-quote-toggle', function() {
    $(this).next('.email-quote').toggle();
    return false;
});
$('.emails').on('click', '.email-pin', function() {
    var email = $(this).parents('.email'),
        data = {action: '+', name: '\\Starred', ids: [email.data('id')]};
    if (email.hasClass('email-pinned')) {
        data.action = '-';
        if (email.parents('.emails-byid').length === 0) {
            data.ids = [email.data('thrid')];
            data.thread = true;
        }
    }
    send('/mark/', data);
    return false;
});
$('.emails-byid').on('click', '.email-text a', function() {
    $(this).attr('target', '_blank');
});

(function() {
var box = $('.compose-to');

box.selectize({
    plugins: ['remove_button', 'restore_on_backspace'],
    delimiter: ',',
    persist: true,
    create: function(input) {
        return {
            value: input,
            text: input
        };
    },
    load: function(query, callback) {
        if (!query.length) return callback();
        $.ajax({
            url: '/search-email/?q=' + encodeURIComponent(query),
            type: 'GET',
            error: function() {
                callback();
            },
            success: function(res) {
                callback(res.slice(0, 10));
            }
        });
    }
});
})();

(function() {
var box = $('.email-labels-edit'),
    url = box.data('baseUrl');

box.selectize({
    plugins: ['remove_button'],
    options: box.data('all'),
    delimiter: ',',
    persist: true,
    valueField: 'name',
    labelField: 'name',
    searchField: ['name'],
    hideSelected: true,
    openOnFocus: true,
    render: {
        item: function(i, e) {
            return (
                '<div><a href="' + e(i.url) + '">' + e(i.name) + '</a></div>'
            );
        },
        option: function(i, e) {
            return '<div>' + e(i.name) + '</div>';
        }
    },
    create: function(input) {
        return {
            name: input,
            url: url + input
        };
    },
    onItemAdd: function(value) {
        mark({action: '+', name: value});
    },
    onItemRemove: function(value) {
        mark({action: '-', name: value});
    }
});
})();
function mark(params) {
    if ($('.emails').hasClass('thread')) {
        params.ids = [$('.email').first().data('thrid')];
        params.thread = true;
    } else {
        var field = $('.emails-byid').length > 0 ? 'id' : 'thrid';
        params.thread = field == 'thrid';
        params.ids = (
            $('.email .email-pick input:checked')
            .map(function() {
                return $(this).parents('.email').data(field);
            })
            .get()
        );
    }
    send('/mark/', params);
}
Mousetrap
    .bind('* a', function() {
        $('.email .email-pick input').prop('checked', true);
    })
    .bind('* n', function() {
        $('.email .email-pick input').prop('checked', false);
    })
    .bind('* r', function() {
        $('.email:not(.email-unread) .email-pick input').prop('checked', true);
    })
    .bind('* u', function() {
        $('.email.email-unread .email-pick input').prop('checked', true);
    })
    .bind('* s', function() {
        $('.email.email-pinned .email-pick input').prop('checked', true);
    })
    .bind('* t', function() {
        $('.email:not(.email-pinned) .email-pick input').prop('checked', true);
    })
    .bind('!', function() {
        mark({action: '+', name: '\\Junk'});
    })
    .bind('#', function() {
        mark({action: '+', name: '\\Trash'});
    })
    .bind('u', function() {
        mark({action: '+', name: '\\Unread'});
    })
    .bind('shift+u', function() {
        mark({action: '-', name: '\\Unread'});
    })
    .bind('i', function() {
        mark({action: '+', name: '\\Inbox'});
    })
    .bind('shift+i', function() {
        mark({action: '-', name: '\\Inbox'});
    })
    .bind('g l', function() {
        location.href = '/';
    });

$([
    ['g i', '\\Inbox'],
    ['g a', '\\All'],
    ['g d', '\\Drafts'],
    ['g s', '\\Sent'],
    ['g u', '\\Unread'],
    ['g p', '\\Starred'],
    ['g !', '\\Junk'],
    ['g #', '\\Trash']
]).each(function(index, item) {
    Mousetrap.bind(item[0], function() {
        location.href = '/emails/?in=' + item[1];
    });
});
