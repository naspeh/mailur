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
    <li><a href="#/label/{{ label.id }}/">
        {{ label.striped_name }} <b>{{ label.recent }}</b>/{{ label.exists }}
    </a></li>
{% endfor %}
</ul>
<div class="panel-one">
</div>
<script src="https://code.jquery.com/jquery.js"></script>
<script>
</script>
</body>
</html>
