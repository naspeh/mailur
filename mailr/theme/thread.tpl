{% extends 'label.tpl' %}

{% block content %}
<h1>
    {{ thread.subject }}
    {% if thread.labels %}
    <span class="email-labels">
    {% for label in thread.labels if not label.hidden %}
        <a href="#{{ url_for('label', label=label.id) }}">{{ label.human_name }}</a>
    {% endfor %}
    </span>
</h1>
{% endif %}
<ul class="thread">
{% for showed, emails in groups %}
    {% if not showed %}
    <div class="email-show"> Show {{ emails|length }} emails</div>
    {% endif %}
    <div class="email-group{% if showed %} email-group-showed{% endif %}">
        {{ render(emails) }}
    </div>
{% endfor %}
</ul>
{% endblock %}

{% macro render(emails) %}
{% for email in emails %}
<li data-id="{{ email.uid }}" class="email{% if email.unread %} email-unread{% endif %}">
    <div class="email-head">
        <span class="email-star{% if email.starred %} email-starred{% endif %}"></span>

        <span class="email-from" title="{{ email.from_|join(', ')|e }}">
            {{ email.from_|map('get_addr')|join(', ') }}
        </span>

        <span class="email-subject">{{ email.human_subject(strip=False) }}</span>

        <span class="email-date">{{ email.date|format_dt }}</span>
    </div>
    <div class="email-body">
    {% if email.html %}
        {{ email.human_html('email-quote') }}
    {% else %}
        <pre>{{ email.text|e }}</pre>
    {% endif %}
    </div>
</li>
{% endfor %}
{% endmacro %}
