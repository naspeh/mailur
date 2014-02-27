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
        <option value="#{{ url_for('label', id=label.id) }}">
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
            var $this = $(this)
                items = $($this.parents('.email'));
            imap_store('X-GM-LABELS', '\\Starred', items, $this.hasClass('email-starred'));
        });

        $('input[name="store"]').click(function() {
            var $this = $(this);
            var items = $this.parents('form')
                .find('input[name="ids"]:checked').parents('.email');
            imap_store($this.data('key'), $this.data('value'), items, $this.data('unset'));
            return false;
        });
        $('input[name="sync"]').click(function() {
            $.get('/sync/').done(function () {
                $(window).trigger('hashchange');
            });
        });
    });
    function imap_store(key, value, items, unset) {
        var ids = [];
        items.each(function() {
            ids.push($(this).data('id'));
        });
        $.post('/imap-store/', {ids: ids, key: key, value: value, unset: unset && 1 || ''})
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
