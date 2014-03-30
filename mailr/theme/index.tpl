{% if layout %}{% extends layout %}{% endif %}
<!DOCTYPE HTML>
<html lang="en">
<head>
    <title>Mail Client</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="/theme/styles.css">
</head>
<body>

<div class="panel" id="panel1" data-box="{{ inbox.url }}">
    <div class="panel-head"></div>
    <div class="panel-body"></div>
</div>
<div class="panel panel-side" id="panel2" data-box="{{ starred.url }}">
    <div class="panel-head"></div>
    <div class="panel-body"></div>
</div>

{# JS stuff #}
<script>
    var CONF = CONF || {}
    CONF.inbox_id = {{ inbox.id }};
    CONF.trash_id = {{ trash.id }};
</script>
<script src="//code.jquery.com/jquery.js"></script>
<script src="/theme/app.js"></script>
{% if conf('opt:ga_id') %}
<script>
  (function(i,s,o,g,r,a,m){i['GoogleAnalyticsObject']=r;i[r]=i[r]||function(){
  (i[r].q=i[r].q||[]).push(arguments)},i[r].l=1*new Date();a=s.createElement(o),
  m=s.getElementsByTagName(o)[0];a.async=1;a.src=g;m.parentNode.insertBefore(a,m)
  })(window,document,'script','//www.google-analytics.com/analytics.js','ga');

  ga('create', '{{ conf("opt:ga_id") }}', '{{ request.host }}');
  ga('send', 'pageview');
</script>
{% endif %}
</body>
</html>
