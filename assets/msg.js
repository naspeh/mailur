import Vue from 'vue';
import tpl from './msg.html';

Vue.component('msg', {
  template: tpl,
  props: {
    msg: { type: Object, required: true },
    editFlags: { type: Function, required: true },
    thread: { type: Boolean, default: false },
    detailed: { type: Boolean, default: false },
    picked: { type: Boolean, default: false },
    details: { type: Function },
    pick: { type: Function },
    hideSubj: { type: Function, default: () => false }
  },
  methods: {
    fetch: q => window.app.fetch(q),
    open: function() {
      if (this.thread) {
        this.fetch(this.msg.query_thread);
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
      return this.editFlags(data, [msg.uid]);
    },
    pin: function(msg) {
      let data = {};
      data[msg.is_pinned ? 'old' : 'new'] = ['\\Flagged'];
      return this.editFlags(data, [msg.uid]);
    }
  }
});
