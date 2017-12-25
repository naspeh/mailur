import Vue from 'vue';
import { call } from './utils.js';
import tpl from './msgs.html';

Vue.component('msgs', {
  template: tpl,
  props: {
    _query: { type: String, default: null },
    split: { type: Boolean, default: false }
  },
  data: function() {
    return {
      perPage: 200,
      query: this._query,
      uids: [],
      msgs: {},
      url: null,
      threads: false,
      picked: [],
      detailed: null
    };
  },
  created: function() {
    this.setMsgs();
    if (this.query) {
      this.fetch(this.query);
    }
  },
  computed: {
    loaded: function() {
      return this.uids.filter(i => this.msgs[i]);
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
    setMsgs: function(msgs, uids) {
      if (!msgs) {
        this.msgs = {};
        //this.picked = [];
      } else {
        this.picked = this.picked.filter(i => this.uids.indexOf(i) != -1);
        this.uids = uids;
        this.msgs = Object.assign({}, this.msgs, msgs);
        this.pics(msgs);
      }
    },
    fetch: function(query, clean = true) {
      if (query) {
        this.query = query;
      }
      if (query && !this.split) {
        window.app.query = query;
      }

      if (clean) {
        this.uids = [];
        this.setMsgs();
      }
      return this.call('post', '/search', {
        q: this.query,
        preload: this.perPage
      }).then(res => {
        this.url = res.msgs_info;
        this.threads = res.threads || false;
        this.setMsgs(res.msgs, res.uids.slice(0, this.perPage));
        this.uids = res.uids;
      });
    },
    pics: msgs => window.app.pics(msgs),
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
    canLoadMore: function() {
      return this.loaded.length < this.uids.length;
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
        this.setMsgs(res, uids)
      );
    },
    page: function(uids) {
      let msgs = [];
      for (const uid of uids) {
        // if (!this.msgs[uid]) console.error(`No message for uid=${uid}`);
        if (this.msgs[uid]) {
          msgs.push(this.msgs[uid]);
        }
      }
      return msgs;
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
          this.fetch(this.query, false).then(() =>
            this.call('post', this.url, { uids: uids }).then(res =>
              this.setMsgs(res, uids)
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
