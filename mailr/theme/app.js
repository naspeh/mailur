(function() {

$(window).ajaxStart(function() {
    $('.loader').show();
    $('input[type="button"]').attr('disabled', true);
});
$(window).ajaxStop(function() {
    $('.loader').hide();
});
$(window).bind('hashchange', function() {
    var url = location.hash.slice(1);
    $('select.labels [value="#' + url + '"]').attr('selected', true);
    $.get(url, function(content) {
        $('.label-active').removeClass('label-active');
        $('.labels a[href="#' + url + '"]').addClass('label-active');

        $('.panel-body').html(content);

        $('.email-star').bind('click', function() {
            var $this = $(this);
            imap_store({
                key: 'X-GM-LABELS',
                value: '\\Starred',
                ids: [$this.parents('.email').data('id')],
                unset: $this.hasClass('email-starred')
            });
        });

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
            .bind('change', function() {
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
