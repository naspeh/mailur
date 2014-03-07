(function() {

$(window).ajaxStart(function() {
    $('.loader').show();
    $('input[type="button"]').attr('disabled', true);
});
$(window).ajaxStop(function() {
    $('.loader').hide();
});
$(window).on('hashchange', function() {
    var url = location.hash.slice(1);
    $('select.labels [value="#' + url + '"]').attr('selected', true);
    $.get(url, function(content) {
        $('.label-active').removeClass('label-active');
        $('.labels a[href="#' + url + '"]').addClass('label-active');

        // Set content
        $('.panel-body').html(content);

        $('.email-line .email-subject').click(function() {
            if (!$(this).parents('.thread').length) {
                window.location.hash = $(this).data('thread');
            }
        });

        $('.email-star').click(function() {
            var $this = $(this);
            imap_store({
                key: 'X-GM-LABELS',
                value: '\\Starred',
                ids: [$this.parents('.email').data('id')],
                unset: $this.hasClass('email-starred')
            });
        });

        if ($('.thread').length) {
            $('.email-subject').click(function() {
                $(this).parents('.email').toggleClass('email-showed');
            });
            $('.email-group-show').click(function() {
                $(this).hide().next('.email-group').show();
            });

            $('.email-quote-switch').click(function() {
                $(this).next('.email-quote').toggle();
            });
        }

        $('input[name="store"]').click(function() {
            var $this = $(this);
            imap_store({
                key: $this.data('key'),
                value: $this.data('value'),
                ids: get_ids($this),
                unset: $this.data('unset')
            });
            return false;
        });
        $('input[name="archive"]').click(function() {
            $.post('/archive/' + get_label() + '/', {ids: get_ids($(this))})
                .done(refresh);
        });
        $('input[name="copy_to_inbox"]').click(function() {
            var url = '/copy/' + get_label() + '/' + CONF.inbox_id + '/';
            $.post(url, {ids: get_ids($(this))}).done(refresh);
        });
        $('input[name="sync"]').click(function() {
            $.get('/sync/' + get_label() + '/').done(refresh);
        });
        $('input[name="sync_all"]').click(function() {
            $.get('/sync/').done(refresh);
        });
    });
    function get_label() {
        return $('select.labels :checked').data('id');
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
});
function refresh() {
    $.get('/labels/', function(content) {
        $('.panel-head').html(content);

        $('select.labels')
            .on('change', function() {
                window.location.hash = $(this).val();
            });
        if (window.location.hash) {
            $('select.labels [value="' + window.location.hash + '"]').attr('selected', true);
            $(window).trigger('hashchange');
        } else {
            $('select.labels').trigger('change');
        }
    });
}
refresh();

// END
})();
