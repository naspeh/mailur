import Vue from 'vue';
import { call } from './utils.js';
import tpl from './msgs.html';

export default Vue.extend({
  template: tpl,
  props: {
    cls: { type: String, required: true },
    query: { type: String, required: true },
    uids: { type: Array, required: true },
    msgs: { type: Object, required: true },
    threads: { type: Boolean, required: true },
    msgs_info: { type: String, required: true },
    fetch: { type: Function, required: true },
    pics: { type: Function, required: true }
  },
  data: function() {
    return {
      perPage: 200,
      picked: [],
      detailed: null
    };
  },
  created: function() {
    this.$mount(`.${this.cls}`);
    this.pics(this.msgs);
  },
  computed: {
    loaded: function() {
      return this.uids.filter(i => this.msgs[i]);
    },
    hidden: function() {
      return this.uids.filter(i => !this.msgs[i]);
    },
    flags: function() {
      let flags = [];
      for (let i of this.picked) {
        flags.push.apply(flags, this.msgs[i].flags);
      }
      return [...new Set(flags)];
    }
  },
  methods: {
    call: call,
    setMsgs: function(msgs) {
      this.picked = this.picked.filter(i => this.uids.indexOf(i) != -1);
      this.msgs = Object.assign({}, this.msgs, msgs);
      this.pics(msgs);
    },
    newQuery: function() {
      this.uids = [];
      this.msgs = {};

      this.fetch(this.query);
    },
    pick: function(uid) {
      let idx = this.picked.indexOf(uid);
      if (idx == -1) {
        this.picked.push(uid);
      } else {
        this.picked.splice(idx, 1);
      }
    },
    pickAll: function() {
      this.picked = this.loaded;
    },
    pickNone: function() {
      this.picked = [];
    },
    link: function() {
      this.call('post', '/thrs/link', { uids: this.picked }).then(() =>
        this.fetch(this.query)
      );
    },
    loadMore: function() {
      let uids = [];
      for (let uid of this.uids) {
        if (!this.msgs[uid]) {
          uids.push(uid);
          if (uids.length == this.perPage) {
            break;
          }
        }
      }
      return this.call('post', this.msgs_info, { uids: uids }).then(res =>
        this.setMsgs(res)
      );
    },
    details: function(uid) {
      if (this.detailed == uid) {
        this.detailed = null;
      } else {
        this.detailed = uid;
      }
    },
    editFlags: function(opts, picked = null) {
      let uids = this.loaded;
      opts = Object.assign({ uids: picked || this.picked }, opts);
      call('post', '/msgs/flag', opts).then(res => {
        if (!res.errors) {
          this.fetch(this.query, { refresh: true }).then(res => {
            this.uids = res.uids;
            this.setMsgs(res.msgs);
            this.call('post', this.msgs_info, { uids: uids }).then(res =>
              this.setMsgs(res)
            );
          });
        }
      });
    },
    archive: function() {
      return this.editFlags({ old: ['#inbox'] });
    },
    del: function() {
      return this.editFlags({ new: ['#trash'] });
    }
  }
});
