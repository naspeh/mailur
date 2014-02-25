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
    });
});
$('select.labels')
    .bind('change', function() {
        if (window.location.hash == $(this).val()) {
            $(window).trigger('hashchange');
        }
        window.location.hash = $(this).val();
    });
if (window.location.hash) {
    $('select.labels [value="' + window.location.hash + '"]').attr('selected', true);
    $('select.labels').trigger('change');
}
</script>
</body>
</html>
