{% if layout %}{% extends layout %}{% endif %}
<!DOCTYPE HTML>
<html lang="en">
<head>
    <title>Mail Client</title>
    <meta charset="utf-8">
    <link rel="stylesheet" href="/theme/styles.css">
</head>
<body>
<div class="panel-one">
    <div class="panel-head">
    {% block labels %}{% if labels %}
        <select class="labels">
        {% for label in labels %}
            <option value="#{{ url_for('label', label=label.id) }}" data-id="{{ label.id }}">
                {{ label.human_name }} <b>{{ label.unread }}</b>/{{ label.exists }}
            </option>
        {% endfor %}
        </select>
    {% endif %}{% endblock %}
    </div>
    <div class="panel-body">
    {% block emails %}{% if emails %}
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
                {% for label in email.full_labels if not label.is_folder %}
                    <a href="#{{ url_for('label', label=label.id) }}">{{ label.human_name }}</a>
                {% endfor %}
                </span>
                {% endif %}

                <span class="email-subject">
                {% if 'thread' in request.path %}
                    <a href="{{ url_for('raw', email=email.id) }}" target="_blank">{{ email.subject }}</a>
                {% else %}
                    <a href="#{{ url_for('gm_thread', id=email.gm_thrid) }}">{{ email.subject }}</a>
                {% endif %}
                </span>

                <span class="email-date" title="{{ email.date|format_dt }}">
                    {{ email.date|humanize_dt }}
                </span>
            </li>
        {% endfor %}
        </ul>
        </form>
    {% endif %}{% endblock %}
    </div>
</div>
<script src="//code.jquery.com/jquery.js"></script>
<script>
    var CONF = CONF || {}
    CONF.inbox_id = {{ inbox.id }};
</script>
<script>
$(window).bind('hashchange', function() {
    var url = location.hash.slice(1);
    $('select.labels [value="#' + url + '"]').attr('selected', true);
    $.get(url, function(content) {
        $('.label-active').removeClass('label-active');
        $('.labels a[href="#' + url + '"]').addClass('label-active');

        $('.panel-one .panel-body').html(content);

        $('.email-star').bind('click', function() {
            var $this = $(this);
            imap_store({
                key: 'X-GM-LABELS',
                value: '\\Starred',
                ids: [$this.parents('.email').data('id')],
                unset: $this.hasClass('email-starred')
            });
        });

        $('input[name="store"]').click(function() {
            var $this = $(this);
            imap_store({
                key: $this.data('key'),
                value: $this.data('value'),
                ids: get_ids($this),
                unset: $this.data('unset')
            });
            return false;
        });
        $('input[name="archive"]').click(function() {
            $.post('/archive/' + get_label() + '/', {ids: get_ids($(this))})
                .done(refresh);
        });
        $('input[name="copy_to_inbox"]').click(function() {
            var url = '/copy/' + get_label() + '/' + CONF.inbox_id + '/';
            $.post(url, {ids: get_ids($(this))}).done(refresh);
        });
        $('input[name="sync"]').click(function() {
            $.get('/sync/' + get_label() + '/').done(refresh);
        });
        $('input[name="sync_all"]').click(function() {
            $.get('/sync/').done(refresh);
        });
    });
    function get_label() {
        return $('select.labels :checked').data('id');
    }
    function get_ids(el) {
        var ids = [];
        el.parents('form').find('input[name="ids"]:checked').parents('.email')
            .each(function() {
                ids.push($(this).data('id'));
            });
        return ids;
    }
    function imap_store(data) {
        data.unset = data.unset && 1 || '';
        $.post('/store/' + get_label() + '/', data).done(refresh);
    }
});
function refresh() {
    $.get('/labels/', function(content) {
        $('.panel-head').html(content)

        $('select.labels')
            .bind('change', function() {
                window.location.hash = $(this).val();
            });
        if (window.location.hash) {
            $('select.labels [value="' + window.location.hash + '"]').attr('selected', true);
            $(window).trigger('hashchange');
        } else {
            $('select.labels').trigger('change');
        }
    })
}
refresh()
</script>
</body>
</html>
