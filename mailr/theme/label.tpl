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
            <li class="email-pick">
                <input type="checkbox" name="ids" value="{{ email.uid }}">
            </li>
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

            <li class="email-subject" {{ {
                'data-raw': url_for('raw', email=email.uid),
                'data-thread': url_for('gm_thread', id=email.gm_thrid)
            }|xmlattr }}>
            {% with subj, text = email.text_line %}
                {% if thread %}
                {{ text or '(no text)' }}
                {% else %}
                <b>{{ subj }}</b>{% if text %} {{ text|e }}{% endif %}
                {% endif %}
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
    <button name="mark" value="archived">Archive</button>
    <button name="copy_to_inbox">Move to Inbox</button>
    <button name="sync">Sync</button>
    <button name="sync_all">Sync all</button>
    <div class="more">
        <b>More >></b>
        <ul>
        {% if label != label.A_TRASH %}
        <li><button name="mark" value="starred">Add star</button></li>
        <li><button name="mark" value="unstarred">Remove star</button></li>
        {% endif %}
        <li><button name="mark" value="read">Read</button></li>
        <li><button name="mark" value="unread">Unread</button></li>
        </ul>
    </div>
    {% block content %}
    <div class="label">
        {{ render(emails) }}
    </div>
    {% endblock %}
</form>
{% endif %}
