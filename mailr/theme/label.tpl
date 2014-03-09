{% macro gravatars(addrs) %}
    {% for addr in addrs %}
        <img src="{{ addr|get_gravatar(16) }}" alt="{{ addr|e }}" title="{{ addr|e }}"/>
    {% endfor %}
{% endmacro %}

{% macro render(emails, thread=False, show=False) %}
<ul class="emails">
{% for email in emails %}
    <li data-id="{{ email.uid }}" class="email
        {% if email.unread %} email-unread{% endif %}
        {% if show %} email-showed{% endif %}
    ">
        <ul class="email-line">
            {% if not thread %}
            <li><input type="checkbox" name="ids" value="{{ email.uid }}"></li>
            {% endif %}

            <li class="email-star{% if email.starred %} email-starred{% endif %}"></li>

            <li class="email-pics">
                {{ gravatars(email.from_) }}
            </li>

            <li class="email-from" title="{{ email.from_|join(', ')|e }}">
                {{ email.from_|map('get_addr_name')|join(', ') }}
            </li>

            {% if not thread and email.labels %}
            <li class="email-labels">
            {% for label in email.full_labels if not label.hidden %}
                <a href="{{ url_for('label', label=label.id) }}">{{ label.human_name }}</a>
            {% endfor %}
            </li>
            {% endif %}

            <li class="email-subject"
                data-raw="{{ url_for('raw', email=email.uid) }}"
                data-thread="{{ url_for('gm_thread', id=email.gm_thrid) }}"
            >
            {% with subj, text = email.text_line %}
                <b>{{ subj }}</b>
                {% if text %} {{ text|e }}{% endif %}
                {% if thread and not text %}(no text){% endif %}
            {% endwith %}
            </li>

            <li class="email-date" title="{{ email.date|format_dt }}">
                {{ email.date|humanize_dt }}
            </li>
        </ul>

        {% if thread %}
        <ul class="email-head">
            <li class="email-star{% if email.starred %} email-starred{% endif %}"></li>

            <li class="email-pics">
                {{ gravatars(email.from_) }}
            </li>

            <li class="email-from" title="{{ email.from_|join(', ')|e }}">
                {{ email.from_|map('get_addr')|join(', ') }}
            </li>

            <li class="email-subject">{{ email.human_subject(strip=False) }}</li>

            <li class="email-date">{{ email.date|format_dt }}</li>
        </ul>
        <div class="email-body">
            {{ email.human_html('email-quote') }}
        </div>
        {% endif %}
    </li>
{% endfor %}
</ul>
{% endmacro %}

{% if emails or groups %}
<form name="emails-form" method="POST">
<input type="button" name="mark" data-name="starred" value="Add star"/>
<input type="button" name="mark" data-name="unstarred" value="Remove star"/>
<input type="button" name="mark" data-name="read" value="Read"/>
<input type="button" name="mark" data-name="unread" value="Unread"/>
<input type="button" name="mark" data-name="archived" value="Archive">
<input type="button" name="copy_to_inbox" value="Copy to Inbox">
<input type="button" name="sync" value="Sync">
<input type="button" name="sync_all" value="Sync all">
{% block content %}
<div class="label">
{{ render(emails) }}
</div>
{% endblock %}
</form>
{% endif %}
