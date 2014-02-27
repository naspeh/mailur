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
        <option value="#{{ url_for('label', id=label.id) }}" data-id="{{ label.id }}">
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
        $('input[name="sync"]').click(function() {
            $.get('/sync/').done(function () {
                $(window).trigger('hashchange');
            });
        });
        $('input[name="archive"]').click(function() {
            var label = $('select.labels :checked').data('id');
            $.post('/archive/' + label + '/', {ids: get_ids($(this))})
                .done(function () {
                    $(window).trigger('hashchange');
                });
        });
    });
    function get_ids(el) {
        var items = el.parents('form').find('input[name="ids"]:checked').parents('.email');
        var ids = [];
        items.each(function() {
            ids.push($(this).data('id'));
        });
        return ids;
    }
    function imap_store(data) {
        data.unset = data.unset && 1 || '';
        $.post('/imap-store/', data)
            .done(function() {
                $.get('/sync/').done(function () {
                    $(window).trigger('hashchange');
                });
            });
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
