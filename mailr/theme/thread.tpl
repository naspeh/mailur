{% extends 'emails.tpl' %}

{% block content %}
{% if groups %}
<base target="_self" href="/">
<h4>
    {{ thread.subject }}
    {% if thread.labels %}
    <span class="email-labels">
    {% for label in thread.labels if not label.hidden %}
        <a href="{{ label.url }}">{{ label.human_name }}</a>
    {% endfor %}
    </span>
</h4>
{% endif %}
<div class="thread">
{% for showed, emails in groups %}
    {% set thread=render(emails, thread=True, show=showed) %}
    {% if not showed and emails|length > few_showed %}
    <div class="email-group-show"> Show {{ emails|length }} emails</div>
    <div class="email-group">{{ thread }}</div>
    {% else %}
    {{ thread }}
    {% endif %}
{% endfor %}
</div>
{% endif %}
{% endblock %}
