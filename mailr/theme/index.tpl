{% if layout %}{% extends layout %}{% endif %}
<!DOCTYPE HTML>
<html lang="en">
<head>
    <title>Mail Client</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="/theme/styles.css">
</head>
<body>

<form class="opts">
<h2>Settings</h2>
<ul>
    <li>
        <input type="checkbox" id="opt-two_panels" class="opt-two_panels">
        <label for="opt-two_panels">Two panels</label>
    </li>
    <li>
        <input type="checkbox" id="opt-fluid" class="opt-fluid">
        <label for="opt-fluid">Fluid width</label>
    </li>
    <li>
        <label>Font size:</label>
        <input type="radio" name="opt-font" class="opt-font" value="normal">normal
        <input type="radio" name="opt-font" class="opt-font" value="bigger">bigger
    </li>
    <li>
        <button name="opts-save" class="opts-save">Save and close</button>
        <label for="opts-save">Press "?" to show again</label>
    </li>
</ul>
</form>

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
