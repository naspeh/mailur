(function() {

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
    function imap_store(data) {
        data.unset = data.unset && 1 || '';
        $.post('/store/' + get_label() + '/', data).done(refresh);
    }
    function start_loader() {
        panel
            .find('.loader').show().end()
            .find('input[type="button"]').attr('disabled', true);
    }
    function stop_loader() {
        panel.find('.loader').hide();
    }

    panel.find('.labels [value="' + url + '"]').attr('selected', true);
    start_loader();
    $.get(url, function(content) {
        stop_loader();
        panel.find('.label-active').removeClass('label-active');
        panel.find('.labels a[href="#' + url + '"]').addClass('label-active');

        // Set content
        panel.find('.panel-body').html(content);

        panel.find('.email-line .email-subject').click(function() {
            if (!$(this).parents('.thread').length) {
                panel.trigger('panel_get', {url: $(this).data('thread')});
            }
            return false;
        });

        panel.find('.email-star').click(function() {
            var $this = $(this);
            imap_store({
                key: 'FLAGS',
                value: '\\Flagged',
                ids: [$this.parents('.email').data('id')],
                unset: $this.hasClass('email-starred')
            });
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

        panel.find('input[name="store"]').click(function() {
            var $this = $(this);
            imap_store({
                key: $this.data('key'),
                value: $this.data('value'),
                ids: get_ids($this),
                unset: $this.data('unset')
            });
            return false;
        });
        panel.find('input[name="archive"]').click(function() {
            $.post('/archive/' + get_label() + '/', {ids: get_ids($(this))})
                .done(refresh);
        });
        panel.find('input[name="copy_to_inbox"]').click(function() {
            var url = '/copy/' + get_label() + '/' + CONF.inbox_id + '/';
            $.post(url, {ids: get_ids($(this))}).done(refresh);
        });
        panel.find('input[name="sync"]').click(function() {
            $.get('/sync/' + get_label() + '/').done(refresh);
        });
        panel.find('input[name="sync_all"]').click(function() {
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
