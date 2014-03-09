(function() {

$(window).ajaxStart(function() {
    $('.loader').show();
    $('input').attr('disabled', true);
});
$(window).ajaxStop(function() {
    $('.loader').hide();
    $('input').attr('disabled', false);
});
$('.panel').on('panel_get', function(event, data) {
    var panel = $(event.target);
    var id = panel.attr('id');
    var url = data && data.url;
    if (url) {
        window.location.hash = [id, url].join('');
        localStorage[id] = url;
    } else {
        url = localStorage.getItem(id);
    }
    url = url ? url : panel.data('box');

    function get_label() {
        return panel.find('select.labels :checked').data('id');
    }
    function get_ids(el) {
        var ids = [];
        el.parents('form').find('input[name="ids"]:checked').parents('.email')
            .each(function() {
                ids.push($(this).data('id'));
            });
        return ids;
    }
    function mark(name, ids) {
        $.post('/mark/' + [get_label(), name].join('/') + '/', {ids: ids}).done(refresh);
    }
    function refresh() {
        panel.trigger('refresh');
    }

    panel.find('.labels [value="' + url + '"]').attr('selected', true);
    $.get(url, function(content) {
        // Set content
        panel.find('.panel-body').html(content);

        panel.find('.email-line .email-subject').click(function() {
            if (!$(this).parents('.thread').length) {
                panel.trigger('panel_get', {url: $(this).data('thread')});
            }
            return false;
        });

        panel.find('.email-pick input').on('change', function() {
            var more = panel.find('.more');
            var checked = panel.find('.email-pick input:checked').parents('.email');

            more.find('li').removeClass('_show');
            more.css({visibility: 'hidden'});

            if (checked.filter('.email-unread').length > 0) {
                more.find('[value="read"]').parents('li').toggleClass('_show');
            }
            if (checked.not('.email-unread').length > 0) {
                more.find('[value="unread"]').parents('li').toggleClass('_show');
            }
            if (checked.find(':not(.email-starred)').length > 0) {
                more.find('[value="starred"]').parents('li').toggleClass('_show');
            }
            if (checked.find('.email-starred').length > 0) {
                more.find('[value="unstarred"]').parents('li').toggleClass('_show');
            }
            if (more.find('li._show').length > 0) {
                more.css({visibility: 'visible'});
            }
        });

        panel.find('.email-star').click(function() {
            var $this = $(this);
            var name = $this.hasClass('email-starred') ? 'unstarred': 'starred';
            mark(name, [$this.parents('.email').data('id')]);
        });

        panel.find('.email-labels a').click(function() {
            panel.trigger('panel_get', {url: $(this).attr('href')});
            return false;
        });

        if (panel.find('.thread').length) {
            panel.find('.email-subject').click(function() {
                $(this).parents('.email').toggleClass('email-showed');
            });
            panel.find('.email-group-show').click(function() {
                $(this).hide().next('.email-group').show();
            });

            panel.find('.email-quote-switch').click(function() {
                $(this).next('.email-quote').toggle();
            });
        }

        panel.find('button[name="mark"]').click(function() {
            var $this = $(this);
            mark($this.val(), get_ids($this));
            return false;
        });
        panel.find('button[name="copy_to_inbox"]').click(function() {
            var url = '/copy/' + get_label() + '/' + CONF.inbox_id + '/';
            $.post(url, {ids: get_ids($(this))}).done(refresh);
        });
        panel.find('button[name="sync"]').click(function() {
            $.get('/sync/' + get_label() + '/').done(refresh);
        });
        panel.find('button[name="sync_all"]').click(function() {
            $.get('/sync/').done(refresh);
        });
    });
});
$('.panel')
    .on('refresh', function(event) {
        $.get('/labels/', function(content) {
            var panel = $(event.target);
            panel.find('.panel-head')
                .html(content)
                .find('.labels').on('change', function() {
                    panel.trigger('panel_get', {url: $(this).find(':selected').val()});
                });
            panel.trigger('panel_get');
        });
    })
    .each(function() {
        $(this).trigger('refresh');
    });

// END
})();
