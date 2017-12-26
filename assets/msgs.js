import Vue from 'vue';
import { call } from './utils.js';
import tpl from './msgs.html';

Vue.component('msgs', {
  template: tpl,
  props: {
    query: { type: String, required: true }
  },
  data: function() {
    return {
      perPage: 200,
      uids: [],
      msgs: {},
      url: null,
      threads: false,
      picked: [],
      detailed: null
    };
  },
  created: function() {
    this.fetch();
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
    pics: msgs => window.app.pics(msgs),
    setMsgs: function(msgs) {
      this.picked = this.picked.filter(i => this.uids.indexOf(i) != -1);
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
        preload: this.perPage
      }).then(res => {
        this.url = res.msgs_info;
        this.threads = res.threads || false;
        this.uids = res.uids;
        this.setMsgs(res.msgs);
      });
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
        this.fetch()
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
      return this.call('post', this.url, { uids: uids }).then(res =>
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
          this.fetch().then(() =>
            this.call('post', this.url, { uids: uids }).then(res =>
              this.setMsgs(res)
            )
          );
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
