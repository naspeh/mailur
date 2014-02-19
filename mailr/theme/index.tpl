<!DOCTYPE HTML>
<html lang="en">
<head>
    <title>Mail Client</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="/theme/styles.css">
</head>
<body>
<ul class="labels">
{% for label in labels %}
    <li class="label"><a href="#{{ url_for('label', id=label.id) }}">
        {{ label.human_name }} <b>{{ label.unread }}</b>/{{ label.exists }}
    </a></li>
{% endfor %}
</ul>
<div class="panel-one">
</div>
<script src="https://code.jquery.com/jquery.js"></script>
<script>
$(window).bind('hashchange', function() {
    var url = location.hash.slice(1);
    $.get(url, function(content) {
        $('.label-active').removeClass('label-active');
        $('.labels a[href="#' + url + '"]').addClass('label-active');

        $('.panel-one').html(content);
    });
});
</script>
</body>
</html>
