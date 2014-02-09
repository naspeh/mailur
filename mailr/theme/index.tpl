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
    <li><a href="#{{ url_for('label', id=label.id) }}">
        {{ label.striped_name }} <b>{{ label.recent }}</b>/{{ label.exists }}
    </a></li>
{% endfor %}
</ul>
<div class="panel-one">
</div>
<script src="https://code.jquery.com/jquery.js"></script>
<script>
$('.labels a').click(function() {
    var url = $(this).attr('href').slice(1);
    $.get(url, function(content) {
        $('.panel-one').html(content);
    });
    return false;
});
</script>
</body>
</html>
