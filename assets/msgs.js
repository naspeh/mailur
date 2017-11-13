import Vue from 'vue';
import { send } from './utils.js';
import tpl from './msgs.html';
import './msgs.css';

Vue.component('Msgs', {
  template: tpl,
  props: {
    threads: { type: Boolean, default: false },
    query: { type: String, required: true }
  },
  data: function() {
    return {
      uids: [],
      perPage: 200,
      pages: []
    };
  },
  created: function() {
    this.setMsgs();
  },
  computed: {
    url: function() {
      return this.threads ? '/thrs' : '/msgs';
    },
    length: function() {
      return this.pages.length
        ? Object.getOwnPropertyNames(this.msgs).length
        : 0;
    },
    app: () => window.app
  },
  methods: {
    setMsgs: function(msgs, uids) {
      if (!msgs) {
        this.msgs = {};
        this.pages = [];
      } else {
        Object.assign(this.msgs, msgs);
        this.pages.push(uids);
        this.pics(msgs);
      }
    },
    fetch: function() {
      return this.send('', {
        q: this.query,
        preload: this.perPage
      }).then(res => {
        this.uids = [];
        this.setMsgs();
        this.setMsgs(res.msgs, res.uids.slice(0, this.perPage));
        this.uids = res.uids;
      });
    },
    send: function(prefix, params) {
      return send(this.url + prefix, params);
    },
    pics: function(msgs) {
      let hashes = [];
      for (let m in msgs) {
        for (let f of msgs[m].from_list) {
          if (f.hash && hashes.indexOf(f.hash) == -1) {
            hashes.push(f.hash);
          }
        }
      }
      if (!hashes.length) {
        return;
      }
      while (hashes.length > 0) {
        let sheet = document.createElement('link');
        let few = encodeURIComponent(hashes.splice(0, 50));
        sheet.href = '/api/avatars.css?size=18&hashes=' + few;
        sheet.rel = 'stylesheet';
        document.body.appendChild(sheet);
      }
    },
    canLoadMore: function() {
      return this.length < this.uids.length;
    },
    loadMore: function() {
      let uids = this.uids.slice(this.length, this.length + this.perPage);
      return this.send('/info', { uids: uids }).then(res =>
        this.setMsgs(res, uids)
      );
    },
    page: function(uids) {
      let msgs = [];
      for (const uid of uids) {
        let msg = this.msgs[uid];
        msg.parsed_uid = uid;
        msg.origin_url = '/api/origin/' + msg.uid;
        msg.parsed_url = '/api/parsed/' + uid;
        msgs.push(msg);
      }
      return msgs;
    }
  }
});
