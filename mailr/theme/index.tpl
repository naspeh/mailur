{% if layout %}{% extends layout %}{% endif %}
<!DOCTYPE HTML>
<html lang="en">
<head>
    <title>Mail Client</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="/theme/styles.css">
</head>
<body>
<div class="panel" id="panel-one">
    <div class="panel-head"></div>
    <div class="panel-body"></div>
</div>
<div class="panel panel-side" id="panel-two">
    <div class="panel-head"></div>
    <div class="panel-body"></div>
</div>

{# JS stuff #}
<script>
    var CONF = CONF || {}
    CONF.inbox_id = {{ inbox.id }};
</script>
<script src="//code.jquery.com/jquery.js"></script>
<script src="/theme/app.js"></script>

</body>
</html>
