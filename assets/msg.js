import Vue from 'vue';
import tpl from './msg.html';

Vue.component('msg', {
  template: tpl,
  props: {
    msg: { type: Object, required: true },
    thread: { type: Boolean, required: true },
    detailed: { type: Boolean, default: false },
    picked: { type: Boolean, default: false }
  },
  methods: {
    fetch: q => window.app.fetch(q),
    details: function() {
      this.$emit('details')
    },
    pick: function() {
      this.$emit('pick')
    },
    open: function() {
      if (this.thread) {
        this.fetch(this.msg.query_thread);
      } else {
        this.details();
      }
    },
    openInSplit: function() {
        window.app.openInSplit(this.msg.query_thread);
    }
  }
});
