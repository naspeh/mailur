{% macro render(emails, thread=False, show=False) %}
<ul class="emails">
{% for email in emails %}
    <li data-id="{{ email.uid }}" class="email
        {% if email.unread %} email-unread{% endif %}
        {% if email.unread or show %} email-showed{% endif %}
    ">
        <ul class="email-line">
            {% if not thread %}
            <li><input type="checkbox" name="ids" value="{{ email.uid }}"></li>
            {% endif %}

            <li class="email-star{% if email.starred %} email-starred{% endif %}"></li>

            <li class="email-from" title="{{ email.from_|join(', ')|e }}">
                {{ email.from_|map('get_addr_name')|join(', ') }}
            </li>

            {% if not thread and email.labels %}
            <li class="email-labels">
            {% for label in email.full_labels if not label.hidden %}
                <a href="#{{ url_for('label', label=label.id) }}">{{ label.human_name }}</a>
            {% endfor %}
            </li>
            {% endif %}

            <li class="email-subject"
                data-raw="#{{ url_for('raw', email=email.uid) }}"
                data-thread="#{{ url_for('gm_thread', id=email.gm_thrid) }}"
            >
            {% with subj, text = email.text_line %}
                <b>{{ subj }}</b>{% if text %} {{ text|e }}{% endif %}
            {% endwith %}
            </li>

            <li class="email-date" title="{{ email.date|format_dt }}">
                {{ email.date|humanize_dt }}
            </li>
        </ul>

        {% if thread %}
        <ul class="email-head">
            <li class="email-star{% if email.starred %} email-starred{% endif %}"></li>

            <li class="email-from" title="{{ email.from_|join(', ')|e }}">
                {{ email.from_|map('get_addr')|join(', ') }}
            </li>

            <li class="email-subject">{{ email.human_subject(strip=False) }}</li>

            <li class="email-date">{{ email.date|format_dt }}</li>
        </ul>
        <div class="email-body">
        {% if email.html %}
            {{ email.human_html('email-quote') }}
        {% else %}
            <pre>{{ email.text|e }}</pre>
        {% endif %}
        </div>
        {% endif %}
    </li>
{% endfor %}
</ul>
{% endmacro %}

{% if emails or groups %}
<form name="emails-form" method="POST">
<input type="button" name="store" value="Add star"
    data-key="X-GM-LABELS" data-value="\Starred">
<input type="button" name="store" value="Remove star"
    data-key="X-GM-LABELS" data-value="\Starred" data-unset="1">
<input type="button" name="store" value="Read"
    data-key="FLAGS" data-value="\Seen">
<input type="button" name="store" value="Unread"
    data-key="FLAGS" data-value="\Seen" data-unset="1">
<input type="button" name="archive" value="Archive">
<input type="button" name="copy_to_inbox" value="Copy to Inbox">
<input type="button" name="sync" value="Sync">
<input type="button" name="sync_all" value="Sync all">
{% block content %}
{{ render(emails) }}
{% endblock %}
</form>
{% endif %}

