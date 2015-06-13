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
            send(location.pathname + location.search, null, function(data) {
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
$('.thread').on('click', '.email-info', function() {
    var email = $(this).parents('.email');
    email.toggleClass('email-show');
    if (email.hasClass('email-show') && !email.hasClass('email-showed')) {
        send(email.data('body-url'), null, function(data) {
            email.replaceWith($(data).find('#' + email.attr('id')));
        });
    }
    return false;
});
$('.thread').on('click', ' .email-details-toggle', function() {
    $(this).parents('.email').find('.email-details').toggle();
    return false;
});
$('.thread').on('click', '.email-quote-toggle', function() {
    $(this).next('.email-quote').toggle();
    return false;
});
$('.emails').on('click', '.email-pin', function() {
    var email = $(this).parents('.email'),
        data = {action: 'add', name: '\\Starred', ids: [email.data('id')]};
    if (email.hasClass('email-pinned')) {
        data.action = 'rm';
        if (email.parents('.emails.thread').length === 0) {
            data.ids = [email.data('thrid')];
            data.thread = true;
        }
    }
    send('/mark/', data);
    return false;
});
$('.thread').on('click', '.email-text a', function() {
    $(this).attr('target', '_blank');
});
$('.email-labels-edit').selectize({
    plugins: ['remove_button', 'restore_on_backspace'],
    delimiter: ',',
    persist: false,
    options: $('.email-labels-edit').data('value').items,
    valueField: 'name',
    labelField: 'name',
    searchField: ['name'],
    render: {
        item: function(i, e) {
            return (
                '<div><span class="item" data-url="' + e(i.url) + '">' +
                e(i.name) +
                '</span></div>'
            );
        },
        option: function(i, e) {
            return '<div>' + e(i.name) + '</div>';
        }
    },
    create: function(input) {
        return {
            name: input,
            url: input
        };
    }
});
$('.email-labels-edit span.item').click(function() {
    window.location = $(this).data('url');
});
function mark(params) {
    params.thread = true;
    if ($('.emails').hasClass('thread')) {
        params.ids = [$('.email').first().data('thrid')];
    } else {
        params.ids = (
            $('.email .email-pick input:checked')
            .map(function() {
                return $(this).parents('.email').data('thrid');
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
    .bind('shift+i', function() {
        mark({action: 'rm', name: '\\Unread'});
    })
    .bind('shift+u', function() {
        mark({action: 'add', name: '\\Unread'});
    });
