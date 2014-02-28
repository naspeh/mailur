<!DOCTYPE HTML>
<html lang="en">
<head>
    <title>Mail Client</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="/theme/all.css">
</head>
<body>
<div class="panel-one">
    <select class="labels">
    {% for label in labels %}
        <option value="#{{ url_for('label', label=label.id) }}" data-id="{{ label.id }}">
            {{ label.human_name }} <b>{{ label.unread }}</b>/{{ label.exists }}
        </option>
    {% endfor %}
    </select>
    <div class="panel-body"
</div>
<script src="//code.jquery.com/jquery.js"></script>
<script>
$(window).bind('hashchange', function() {
    var url = location.hash.slice(1);
    $('select.labels [value="#' + url + '"]').attr('selected', true);
    $.get(url, function(content) {
        $('.label-active').removeClass('label-active');
        $('.labels a[href="#' + url + '"]').addClass('label-active');

        $('.panel-one .panel-body').html(content);

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
            $.post('/copy/' + get_label() + '/' + 4 + '/', {ids: get_ids($(this))})
                .done(refresh);
        });
        $('input[name="sync"]').click(function() {
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
    function refresh() {
        $(window).trigger('hashchange');
    }
});
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
</script>
</body>
</html>
