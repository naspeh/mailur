{% if emails %}
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
<ul class="emails">
{% for email in emails %}
    <li data-id="{{ email.uid }}" class="email{% if email.unread %} email-unread{% endif %}">
        <span><input type="checkbox" name="ids" value="{{ email.uid }}"></span>
        <span class="email-star{% if email.starred %} email-starred{% endif %}"></span>

        <span class="email-from" title="{{ email.from_|join(', ')|e }}">
            {{ email.from_|map('get_addr_name')|join(', ') }}
        </span>
        {#
        <span class="email-pics">
        {% for addr in email.from_ %}
            <img src="{{ addr|get_gravatar }}?s=20"  alt="{{ addr|e }}" />
        {% endfor %}
        </span>
        #}

        {% if email.labels %}
        <span class="email-labels">
        {% for label in email.full_labels if not label.hidden %}
            <a href="#{{ url_for('label', label=label.id) }}">{{ label.human_name }}</a>
        {% endfor %}
        </span>
        {% endif %}

        <span class="email-subject">
        {% with subj, text = email.text_line %}
            {% if 'thread' in request.path %}
            <a href="{{ url_for('raw', email=email.id) }}" target="_blank">
            {% else %}
            <a href="#{{ url_for('gm_thread', id=email.gm_thrid) }}">
            {% endif %}
                <b>{{ subj }}</b>{% if text %} - {{ text|e }}{% endif %}
            </a>
        {% endwith %}
        </span>

        <span class="email-date" title="{{ email.date|format_dt }}">
            {{ email.date|humanize_dt }}
        </span>
    </li>
{% endfor %}
</ul>
{% endblock %}
</form>
{% endif %}
