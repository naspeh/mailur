import Vue from 'vue';
import { call } from './utils.js';
import tpl from './thread.html';

export default Vue.extend({
  template: tpl,
  props: {
    cls: { type: String, required: true },
    query: { type: String, required: true },
    uids: { type: Array, required: true },
    msgs: { type: Object, required: true },
    thread: { type: Object, required: true },
    same_subject: { type: Array, required: true },
    msgs_info: { type: String, required: true },
    fetch: { type: Function, required: true },
    pics: { type: Function, required: true }
  },
  data: function() {
    return {
      preload: 4,
      detailed: []
    };
  },
  created: function() {
    this.$mount(`.${this.cls}`);
    this.pics(this.msgs);
  },
  computed: {
    hidden: function() {
      return this.uids.filter(i => !this.msgs[i]);
    }
  },
  methods: {
    call: call,
    setMsgs: function(msgs) {
      this.msgs = Object.assign({}, this.msgs, msgs);
      this.pics(msgs);
    },
    newQuery: function() {
      this.uids = [];
      this.msgs = {};
      this.thread = null;

      this.fetch(this.query);
    },
    loadAll: function() {
      return this.call('post', this.msgs_info, {
        uids: this.hidden,
        hide_flags: this.thread.flags
      }).then(msgs => this.setMsgs(msgs));
    },
    details: function(uid) {
      let idx = this.detailed.indexOf(uid);
      if (idx == -1) {
        this.detailed.push(uid);
      } else {
        this.detailed.splice(idx, 1);
      }
    },
    editFlags: function(opts, picked = null) {
      let preload = this.hidden.length > 0 ? this.preload : null;
      opts = Object.assign({ uids: picked || this.uids }, opts);
      call('post', '/msgs/flag', opts).then(res => {
        if (!res.errors) {
          this.fetch(this.query, { refresh: true, preload: preload }).then(
            res => {
              this.uids = res.uids;
              this.thread = res.thread;
              this.setMsgs(res.msgs);
            }
          );
        }
      });
    }
  }
});
