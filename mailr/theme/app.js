(function() {

function sync() {
    $.get('/sync/');
    setTimeout(sync, 30000);
}
sync();

$(document).ajaxStart(function() {
    $('.refresh.loader').show();
    $('input, button, select').attr('disabled', true);
});
$(document).ajaxStop(function() {
    $('.refresh.loader').hide();
    $('.loader').removeClass('loader');
    $('input, button, select').attr('disabled', false);
});
$('.panel').on('loader', function(event, element) {
    var panel = $(event.target);
    panel.find('.refresh').addClass('loader');
    if (element) {
        $(element).addClass('loader');
    }
});
$('.panel').on('panel_get', function(event, data) {
    var panel = $(event.target);
    var panel_id = panel.attr('id');
    var storage = Storage(panel_id);

    if (window.location.hash == '#reset') {
        storage.reset();
    }

    var url = data && data.url;
    if (url) {
        var hash = [panel_id, url].join('');
        window.location.hash = hash;
        storage.set('url', url);
        storage.set('uids', []); // Reset picked uids
    } else {
        url = storage.get('url');
    }
    url = url ? url : panel.data('box');
    if (url.indexOf('/emails/') === 0) {
        storage.set('label', url);
    }
    var label_id = storage.get('label');
    label_id = label_id && parseInt(label_id.split('=')[1]);

    function Storage(panel_id) {
        var defaults = {url: null, uids: [], label: null};
        var storage = localStorage[panel_id];
        storage = storage ? JSON.parse(storage) : defaults;

        var me = {
            get: function(key) {
                return storage[key];
            },
            set: function(key, val) {
                storage[key] = val;
                me.save();
            },
            addChild: function(key, val) {
                storage[key].push(val);
                me.save();
            },
            delChild: function(key, val) {
                var index = storage[key].indexOf(uid);
                storage[key].splice(index, 1);
            },
            reset: function() {
                storage = defaults;
                me.save();
                return storage;
            },
            save: function() {
                localStorage[panel_id] = JSON.stringify(storage);
            }
        };
        return me;
    }
    function mark(name, ids, callback) {
        callback = callback || refresh;
        $.post('/mark/' + name + '/', {ids: ids, label: label_id}).done(callback);
    }
    function refresh() {
        panel.trigger('panel_get');
    }

    panel.trigger('loader');
    $.get(url, function(content) {
        // Set content
        panel.html(content);

        panel.find('.labels [value="' + url + '"]').prop('selected', true);
        panel.find('.panel-head')
            .find('.labels').on('change', function() {
                panel.trigger('panel_get', {url: $(this).find(':selected').val()});
            });

        panel.find('.email-line .email-info').click(function() {
            if (!$(this).parents('.thread').length) {
                panel.trigger('panel_get', {url: $(this).parents('.email').data('thread')});
            }
            return false;
        });

        panel.find('.email-pick input')
            .each(function() {
                var uid = $(this).val();
                if (storage.get('uids').indexOf(uid) > -1) {
                    $(this).attr('checked', true);
                } else if ($(this).is(':checked')) {
                    storage.addChild('uids', uid);
                }
            })
            .on('change', function() {
                var uid = $(this).val();
                if ($(this).is(':checked') && storage.get('uids').indexOf(uid) == -1) {
                    storage.addChild('uids', uid);
                } else {
                    storage.delChild('uids', uid);
                }
                stored_data(true);
                panel.trigger('refresh_buttons');
            });
        panel.find('.email-star').click(function() {
            panel.trigger('loader');
            var $this = $(this);
            var name = $this.hasClass('email-starred') ? 'unstarred': 'starred';
            mark(name, [$this.parents('.email').data('id')]);
        });

        panel.find('.email-labels a, .email-filter').click(function() {
            panel.trigger('panel_get', {url: $(this).attr('href')});
            return false;
        });

        if (panel.find('.thread').length) {
            panel.find('.email-info').click(function() {
                $(this).parents('.email').toggleClass('email-showed');
            });
            panel.find('.email-group-show').click(function() {
                $(this).hide().next('.email-group').show();
            });

            panel.find('.email-quote-switch').click(function() {
                $(this).next('.email-quote').toggle();
            });
        }

        panel.on('refresh_buttons', function() {
            var buttons = panel.find('button');
            var checked = panel.find('.email-pick input:checked').parents('.email');

            buttons.hide();
            buttons.filter('.refresh').show();
            if (checked.length > 0) {
                buttons.filter('[name="copy_to_inbox"]').show();
                if (label_id != CONF.trash_id) {
                    buttons.filter('[value="archived"]').show();
                    buttons.filter('[value="deleted"]').show();
                }
            }
            if (checked.filter('.email-unread').length > 0) {
                buttons.filter('[value="read"]').show();
            }
            if (checked.not('.email-unread').length > 0) {
                buttons.filter('[value="unread"]').show();
            }
            if (checked.find('.email-star:not(.email-starred)').length > 0) {
                buttons.filter('[value="starred"]').show();
            }
            if (checked.find('.email-starred').length > 0) {
                buttons.filter('[value="unstarred"]').show();
            }
        }).trigger('refresh_buttons');

        panel.find('button[name="mark"]').click(function() {
            panel.trigger('loader', this);
            var $this = $(this);
            var callback = refresh;
            if ($this.val() == 'deleted' || ($this.val() == 'archived' && label_id == CONF.inbox_id)) {
                callback = function() {
                    panel.trigger('panel_get', {url: storage.get('label')});
                };
            }
            mark($this.val(), storage.get('uids'), callback);
            return false;
        });
        panel.find('button[name="copy_to_inbox"]').click(function() {
            panel.trigger('loader', this);
            var url = '/copy/' + label_id + '/' + CONF.inbox_id + '/';
            $.post(url, {ids: storage.get('uids')}).done(refresh);
            return false;
        });
        panel.find('button[name="refresh"]').click(function() {
            panel.trigger('loader', this);
            sync();
            refresh();
            return false;
        });
    });
});
$('.panel')
    .each(function() {
        $(this).trigger('panel_get');
    });

$(window).on('hashchange', function() {
    var parts = window.location.hash.split('/');
    var panel = $(parts.shift());
    if (panel.length) {
        panel.trigger('panel_get', {url: '/' + parts.join('/')});
    }
});

// END
})();
