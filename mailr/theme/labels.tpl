{% if labels %}
<select class="labels">
{% for label in labels %}
    <option value="{{ label.url }}" data-id="{{ label.id }}">
        {{ label.human_name }} <b>{{ label.unread }}</b>/{{ label.exists }}
    </option>
{% endfor %}
</select>
{#<button name="compose" class="btn-compose">Compose</button>#}
<div class="loader-fixed">Loading..</div>

{#<button name="sync_all">Sync all</button>#}
<button name="sync">Sync</button>
<button name="mark" value="archived">Archive</button>
<button name="mark" value="deleted">Delete</button>
<button name="copy_to_inbox">Move to Inbox</button>
{#
<button name="mark" value="starred">Add star</button>
<button name="mark" value="unstarred">Remove star</button>
#}
<button name="mark" value="read">Read</button>
<button name="mark" value="unread">Unread</button>
{% endif %}
