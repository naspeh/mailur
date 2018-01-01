import Vue from 'vue';
import tpl from './msg.html';

Vue.component('msg', {
  template: tpl,
  props: {
    msg: { type: Object, required: true },
    body: { type: String },
    thread: { type: Boolean, default: false },
    opened: { type: Boolean, default: false },
    open: { type: Function, required: true },
    detailed: { type: Boolean, default: false },
    details: { type: Function, required: true },
    picked: { type: Boolean, default: false },
    pick: { type: Function },
    editTags: { type: Function, required: true }
  },
  methods: {
    openInMain: q => window.app.openInMain(q),
    openDefault: function() {
      if (this.thread) {
        this.openInMain(this.msg.query_thread);
      } else {
        this.details(this.msg.uid);
      }
    },
    openInSplit: function() {
      window.app.openInSplit(this.msg.query_thread);
    },
    read: function(msg) {
      let data = {};
      data[msg.is_unread ? 'new' : 'old'] = ['\\Seen'];
      return this.editTags(data, [msg.uid]);
    },
    pin: function(msg) {
      let data = {};
      data[msg.is_pinned ? 'old' : 'new'] = ['\\Flagged'];
      return this.editTags(data, [msg.uid]);
    }
  }
});
