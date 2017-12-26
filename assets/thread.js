import Vue from 'vue';
import { call } from './utils.js';
import tpl from './thread.html';

Vue.component('thread', {
  template: tpl,
  props: {
    query: { type: String, required: true }
  },
  data: function() {
    return {
      preload: 4,
      uids: [],
      msgs: {},
      thread: null,
      same_subject: [],
      url: null,
      detailed: []
    };
  },
  created: function() {
    this.fetch();
  },
  computed: {
    hidden: function() {
      return this.uids.filter(i => !this.msgs[i]);
    }
  },
  methods: {
    call: call,
    pics: msgs => window.app.pics(msgs),
    setMsgs: function(msgs) {
      this.msgs = Object.assign({}, this.msgs, msgs);
      this.pics(msgs);
    },
    newQuery: function() {
      this.$emit('update:query', this.$refs.query.value);

      this.uids = [];
      this.msgs = {};

      this.$nextTick(() => this.fetch());
    },
    fetch: function() {
      return this.call('post', '/search', {
        q: this.query,
        preload: this.preload
      }).then(res => {
        this.url = res.msgs_info;
        this.thread = res.thread;
        this.uids = res.uids;
        this.same_subject = res.same_subject;
        this.setMsgs(res.msgs);
      });
    },
    loadAll: function() {
      return this.call('post', this.url, {
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
      this.preload = this.hidden.length > 0 ? this.preload : null;
      opts = Object.assign({ uids: picked || this.uids }, opts);
      call('post', '/msgs/flag', opts).then(res => {
        if (!res.errors) {
          this.fetch();
        }
      });
    }
  }
});
