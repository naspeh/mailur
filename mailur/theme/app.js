(function() {
var ws = null, handlers = {}, messages = [];

connect();

$.get('/init/', {'offset': new Date().getTimezoneOffset() / 60});
if ($('.thread .email-unread').length !== 0) {
    mark({action: '-', name: '\\Unread'}, function() {});
}
if ($('.emails-byid').length === 0) {
    $('.emails').on('click', '.email-info', function() {
        var email = $(this).parents('.email');
        location.href = email.data('thread-url');
    });
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
$('.emails').on('click', ' .email-a-details', function() {
    $(this).parents('.email-details').find('.email-extra').toggle();
    return false;
});
$('.emails').on('click', ' .email-a-delete', function() {
    mark({
        action: '+',
        name: '\\Trash',
        ids: [$(this).parents('.email').data('id')]
    });
    return false;
});
$('.emails').on('click', '.email-quote-toggle', function() {
    $(this).next('.email-quote').toggle();
    return false;
});
$('.emails').on('click', '.email-pin', function() {
    var email = $(this).parents('.email'),
        data = {action: '+', name: '\\Pinned', ids: [email.data('id')]};
    if (email.hasClass('email-pinned')) {
        data.action = '-';
        if (email.parents('.emails-byid').length === 0) {
            data.ids = [email.data('thrid')];
            data.thread = true;
            data.last = $('.emails').data('last');
        }
    }
    mark(data);
    return false;
});
$('.emails-byid').on('click', '.email-text a', function() {
    $(this).attr('target', '_blank');
});
$('.emails').on('images', '.email-attachments', function() {
    $('.email-f-image').swipebox({
        hideBarsDelay: 3000
    });
});
$('.emails .email-attachments').trigger('images');
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
        mark({action: '+', name: '\\Spam'});
    }],
    [['m #', '#'] , 'Delete', function() {
        mark({action: '+', name: '\\Trash'});
    }],
    [['m u', 'm shift+r'], 'Mark as unread', function() {
        mark({action: '+', name: '\\Unread'}, function() {});
    }],
    [['m r', 'm shift+u'], 'Mark as read', function() {
        mark({action: '-', name: '\\Unread'}, function() {});
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
        location.href = $('.email:last').data('reply-url');
    }],
    [['r a'], 'Reply all', function() {
        location.href = $('.email:last').data('replyall-url');
    }],
    [['c'], 'Compose', function() {
        location.href = '/compose/';
    }],
    [['g i'], 'Go to Inbox', goToLabel('\\Inbox')],
    [['g d'], 'Go to Drafts', goToLabel('\\Drafts')],
    [['g s'], 'Go to Sent messages', goToLabel('\\Sent')],
    [['g u'], 'Go to Unread conversations', goToLabel('\\Unread')],
    [['g p'], 'Go to Pinned conversations', goToLabel('\\Pinned')],
    [['g a'], 'Go to All mail', goToLabel('\\All')],
    [['g !'], 'Go to Spam', goToLabel('\\Spam')],
    [['g #'], 'Go to Trash', goToLabel('\\Trash')],
    [['?'], 'Toggle keyboard shortcut help', function() {
        $('.help-toggle').click();
    }]
];
$(hotkeys).each(function(index, item) {
    Mousetrap.bind(item[0], item[2], 'keyup');
});
$('body').on('click', '.help-toggle', function() {
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
});
function goToLabel(label) {
    return function() {
        location.href = '/emails/?in=' + label;
    };
}
})();

(function() {
/* Compose */
var form = $('.compose'),
    text = form.find('textarea'),
    ok = form.find('.compose-send');

if (form.length === 0) return;
form.find('.compose-to').selectize({
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

ok.click(function() {
    form.submit();
});
tabOverride.set(text[0]);
text.each(function() {
    Mousetrap(this)
        .bind('ctrl+enter', function() {
            ok.focus().click();
        });
});
text.on('input', function() {
    $('.compose-preview').click();
});
$('.compose-preview').click(function() {
    var data = {'body': $('.compose-body').val()};
    if ($('.compose-quoted').is(':checked')) {
        data.quote = $('.compose-quote').val();
    }
    send('/preview/', data, function(data) {
        $('.email-html').html(data).show();
    });
}).click();
$('.compose-quoted').on('change', function() {
    $('.compose-preview').click();
});
})();

(function() {
/* Edit labels */
$('.email-mark-del, .email-mark-spam, .email-mark-arch')
    .on('click', function() {
        $this = $(this);
        mark({
            action: $this.data('action') || '+',
            name: $this.data('label')
        });
    });

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
    copyClassesToDropdown: false,
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
    onChange: function(val) {
        if (val.split(',').sort().toString() == getLabels().sort().toString()) {
            $('.email-labels-wrap').removeClass('changed');
        } else {
            $('.email-labels-wrap').addClass('changed');
        }
    }
});

var selectize = box[0].selectize;
selectize.setValue(getLabels());

var refreshOptions = selectize.refreshOptions.bind(selectize);
selectize.refreshOptions = function(triggerDropdown) {
    if (this.$control_input.val()) {
        refreshOptions(triggerDropdown);
    }
};

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
        .bind(['esc'], function() {
            selectize.close();
        })
        .bind(['backspace'], function() {
            refreshOptions(true);
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
            send('/sidebar/', null, function(data) {
                $('.labels').html($(data).find('.labels'));
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
        url += (url.indexOf('?') === -1 ? '?' : '&') + 'fmt=body';
        var resp = {url: url, payload: data, uid: guid()};
        ws.send(JSON.stringify(resp));
        if (callback) {
            handlers[resp.uid] = callback;
        }
    } else {
        messages = [function() {send(url, data, callback);}].concat(messages);
    }
}
function mark(params, callback) {
    params.last = $('.emails').data('last');

    if (!params.ids) {
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
    }
    callback = callback || function(data) {
        location.reload();
        // var path = location.pathname + location.search;
        // send(path, null, function(data) {
        //     $('body').html(data);
        // });
    };
    send('/mark/', params, callback);
}
})();
