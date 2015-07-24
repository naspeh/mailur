(function() {
var ws = null, handlers = {}, messages = [];

connect();

if ($('.thread .email-unread').length !== 0) {
    mark({action: '-', name: '\\Unread'});
}
$('.emails-byid').on('click', '.email-info', function() {
    var email = $(this).parents('.email');
    email.toggleClass('email-show');
    if (email.hasClass('email-show') && !email.hasClass('email-showed')) {
        send(email.data('body-url'), null, function(data) {
            var body = $(data).find('#' + email.attr('id') + ' .email-body');
            email.find('.email-body').replaceWith(body);
            body.find('.email-attachments').trigger('images');
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
$('.emails').on('images', '.email-attachments', function() {
    $(this).magnificPopup({
        delegate: 'a',
        type: 'image',
        tLoading: 'Loading image #%curr%...',
        gallery: {
            enabled: true,
            navigateByImgClick: true,
            preload: [0, 1]
        },
        image: {
            tError: '<a href="%url%">The image #%curr%</a> could not be loaded.',
            titleSrc: function(item) {
                return item.el.html();
            }
        }
    });
});
(function() {
/* Keyboard shortcuts */
var hotkeys = [
    [['s a', '* a'], 'Select all conversations', function() {
        $('.email .email-pick input').prop('checked', true);
    }],
    [['s n', '* n'], 'Deselect all conversations', function() {
        $('.email .email-pick input').prop('checked', false);
    }],
    [['s r', '* r'], 'Select read conversations', function() {
        $('.email:not(.email-unread) .email-pick input').prop('checked', true);
    }],
    [['s u', '* u'], 'Select unread conversations', function() {
        $('.email.email-unread .email-pick input').prop('checked', true);
    }],
    [['s p', '* s'], 'Select pinned conversations', function() {
        $('.email.email-pinned .email-pick input').prop('checked', true);
    }],
    [['s shift+p', '* t'], 'Select unpinned conversations', function() {
        $('.email:not(.email-pinned) .email-pick input').prop('checked', true);
    }],
    [['m !', '!'], 'Report as spam', function() {
        mark({action: '+', name: '\\Junk'});
    }],
    [['m #', '#'] , 'Delete', function() {
        mark({action: '+', name: '\\Trash'});
    }],
    [['m u', 'm shift+r'], 'Mark as unread', function() {
        mark({action: '+', name: '\\Unread'});
    }],
    [['m r', 'm shift+u'], 'Mark as read', function() {
        mark({action: '-', name: '\\Unread'});
    }],
    [['m i', 'm shift+a'], 'Move to Inbox', function() {
        mark({action: '+', name: '\\Inbox'});
    }],
    [['m a', 'm shift+i'], 'Move to Archive', function() {
        mark({action: '-', name: '\\Inbox'});
    }],
    [['m l'], 'Edit labels', function() {
        $('.email-labels-edit input').focus();
    }],
    [['r r'], 'Reply', function() {
        location.href = $('.email:last').data('replyUrl');
    }],
    [['r a'], 'Reply all', function() {
        location.href = $('.email:last').data('replyallUrl');
    }],
    [['g l'], 'Go to Labels', function() {
        location.href = '/';
    }],
    [['g i'], 'Go to Inbox', goToLabel('\\Inbox')],
    [['g d'], 'Go to Drafts', goToLabel('\\Drafts')],
    [['g s'], 'Go to Sent messages', goToLabel('\\Sent')],
    [['g u'], 'Go to Unread conversations', goToLabel('\\Unread')],
    [['g p'], 'Go to Pinned conversations', goToLabel('\\Starred')],
    [['g a'], 'Go to All mail', goToLabel('\\All')],
    [['g !'], 'Go to Spam', goToLabel('\\Junk')],
    [['g #'], 'Go to Trash', goToLabel('\\Trash')],
    [['?'], 'Toggle keyboard shortcut help', function() {
        var help = $('.help');
        if (!help.hasClass('help-loaded')) {
            var html = '';
            $(hotkeys).each(function(index, item) {
                html += '<div><b>' + item[0][0] + '</b>: ' + item[1] + '</div>';
            });
            help.append(html);
            help.addClass('help-loaded');
            help.find('.help-close').on('click', function() {
                help.trigger('hide');
            });
        }
        help.on({
            'hide': function() {
                Mousetrap.unbind('esc');
                help.hide();
            },
            'show': function() {
                Mousetrap.bind('esc', function() {
                    help.hide();
                });
                help.show();
            }
        });
        if (help.is(':hidden')) {
            help.trigger('show');
        } else {
            help.trigger('hide');
        }
    }]
];
$(hotkeys).each(function(index, item) {
    Mousetrap.bind(item[0], item[2], 'keyup');
});
function goToLabel(label) {
    return function() {
        location.href = '/emails/?in=' + label;
    };
}
})();

(function() {
/* Compose */
var box = $('.compose-to');

if (box.length === 0) return;
box.selectize({
    plugins: ['remove_button', 'restore_on_backspace'],
    delimiter: ',',
    persist: true,
    create: true,
    hideSelected: true,
    openOnFocus: false,
    closeAfterSelect: true,
    copyClassesToDropdown: true,
    load: function(q, callback) {
        if (!q.length) return callback();
        send('/search-email/?q=' + encodeURIComponent(q), null, function(res) {
            callback(JSON.parse(res));
        });
    }
});

$('.compose-preview').click(function() {
    $.post('/preview/', {'body': $('.compose-body').val()}, function(data) {
        $('.email-html').html(data).show();
    });
});
})();

(function() {
/* Edit labels */
var box = $('.email-labels-input'),
    container = box.parents('.email-labels-edit'),
    url = box.data('baseUrl');

if (box.length === 0) return;
box.selectize({
    plugins: ['remove_button'],
    items: box.data('items'),
    options: box.data('all'),
    delimiter: ',',
    persist: true,
    valueField: 'name',
    labelField: 'name',
    searchField: ['name'],
    hideSelected: true,
    openOnFocus: false,
    closeAfterSelect: true,
    copyClassesToDropdown: true,
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
    }
});

var selectize = box[0].selectize;
selectize.setValue(getLabels());

$('.emails').on('change', '.email-pick', function() {
    selectize.setValue(getLabels());
});

var ok = $('.email-labels-ok'),
    cancel = $('.email-labels-cancel');

ok.on('click', function() {
    mark({
        action: '=',
        name: selectize.getValue().split(','),
        old_name: getLabels()
    });
    return false;
});
cancel.on('click', function() {
    selectize.setValue(getLabels());
});
$(container.find('input')).each(function() {
    Mousetrap(this)
        .bind(['backspace', 'esc'], function() {
            selectize.close();
        })
        .bind('esc esc', function() {
            cancel.focus().click();
        })
        .bind('ctrl+enter', function() {
            ok.focus().click();
        });
});

function getLabels() {
    var labels = (box.data('items') || []).slice(),
        checked = $('.email-pick input:checked, .thread .email-pick input');

    checked.each(function() {
        var email = $(this).parents('.email');
        $.each(email.data('labels') || [], function(index, value) {
            if ($.inArray(value, labels) == -1) {
                labels.push(value);
            }
        });
    });
    container.toggle(checked.length !== 0);
    return labels;
}
})();

/* Related functions */
function connect() {
    ws = new WebSocket('ws://localhost:9000');
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
    if (ws && ws.readyState === ws.OPEN) {
        url = 'http://localhost' + url;
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

})();
