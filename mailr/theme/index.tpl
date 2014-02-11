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
        {{ label.striped_name }} <b>{{ label.recent }}</b>/{{ label.exists }}
    </a></li>
{% endfor %}
</ul>
<div class="panel-one">
</div>
<script src="https://code.jquery.com/jquery.js"></script>
<script>
$('.labels a').click(function() {
    var $this = $(this);
    var url = $this.attr('href').slice(1);
    $.get(url, function(content) {
        $('.label-active').removeClass('label-active');
        $this.addClass('label-active');

        $('.panel-one').html(content);
    });
});
</script>
</body>
</html>
