import Vue from 'vue';
import './favicon.png';
import './picker.js';
import './tags.js';
import './editor.js';
import './filters.js';
import './msg.js';
import { call } from './utils.js';
import msgs from './msgs.js';
import tpl from './app.html';

Vue.component('app', {
  template: tpl,
  data: function() {
    let splitIsPossible = window.innerWidth > 1200;
    return {
      tags: window.data.tags.info,
      tagIds: window.data.tags.ids,
      tagIdsEdit: window.data.tags.ids_edit,
      addrs: [],
      picSize: 20,
      tagCount: 5,
      opts: {
        bigger: false,
        fixPrivacy: false,
        query: null,
        split: splitIsPossible,
        splitQuery: ':threads tag:#inbox',
        filters: false
      },
      optsKey: `${window.data.user}:opts`,
      splitIsPossible: splitIsPossible
    };
  },
  created: function() {
    window.app = this;
  },
  mounted: function() {
    let opts = window.localStorage.getItem(this.optsKey);
    if (opts) {
      this.opts = JSON.parse(opts);
      this.reloadOpts();
    }

    this.openFromHash();

    window.onhashchange = () => {
      this.openFromHash();
    };
  },
  computed: {
    allTags: function() {
      let tags = [];
      for (let i of this.tagIds) {
        let tag = this.tags[i];
        if (tag.unread || tag.pinned) {
          tags.push(i);
        }
      }
      return tags;
    }
  },
  methods: {
    refreshData: function() {
      call('get', '/index-data').then(res => {
        if (res.errors) {
          return;
        }
        window.data = res;
        let tags = res.tags;
        this.tags = Object.assign({}, tags.info);
        this.tagIds = tags.ids;
        this.tagIdsEdit = tags.ids_edit;
      });
    },
    setOpt: function(name, value) {
      this.opts[name] = value;
      window.localStorage.setItem(this.optsKey, JSON.stringify(this.opts));
      this.reloadOpts();
    },
    toggleOpt: function(name) {
      this.setOpt(name, !this.opts[name]);
    },
    reloadOpts: function() {
      let html = document.querySelector('html');
      html.classList.toggle('opt--bigger', this.opts.bigger);
      html.classList.toggle('opt--fix-privacy', this.opts.fixPrivacy);
      if (!this.split && this.opts.split && this.opts.splitQuery) {
        this.openInSplit(this.opts.splitQuery);
      }
    },
    compose: function() {
      this.main
        .call('get', '/compose')
        .then(res => this.openInMain(res.query_edit));
    },
    openFromHash: function() {
      let q = decodeURIComponent(location.hash.slice(1));
      if (q) {
        // pass
      } else if (this.opts.query !== null) {
        q = this.opts.query;
      } else {
        q = ':threads tag:#inbox';
      }
      if (!this.main || this.main.query != q) {
        this.openInMain(q);
      }
    },
    openInMain: function(q) {
      window.location.hash = q;
      this.opts.query == q || this.setOpt('query', q);

      let view = msgs({
        cls: 'main',
        query: q,
        open: this.openInMain,
        pics: this.pics
      });
      if (this.main) {
        this.main.newQuery(q);
      } else {
        view.mount();
      }
      this.main = view;
    },
    openInSplit: function(q) {
      this.opts.split || this.setOpt('split', true);
      this.opts.splitQuery == q || this.setOpt('splitQuery', q);

      let view = msgs({
        cls: 'split',
        query: q,
        open: this.openInSplit,
        pics: this.pics
      });
      if (this.split) {
        this.split.newQuery(q);
      } else {
        view.mount();
      }
      this.split = view;
    },
    logout: function() {
      window.location = '/logout';
    },
    pics: function(msgs) {
      let hashes = [];
      for (let m in msgs) {
        for (let f of msgs[m].from_list) {
          if (
            f.hash &&
            hashes.indexOf(f.hash) == -1 &&
            this.addrs.indexOf(f.hash) == -1
          ) {
            hashes.push(f.hash);
          }
        }
      }
      if (hashes.length == 0) {
        return;
      }
      this.addrs = this.addrs.concat(hashes);
      while (hashes.length > 0) {
        let sheet = document.createElement('link');
        let few = encodeURIComponent(hashes.splice(0, 50));
        sheet.href = `/avatars.css?size=${this.picSize}&hashes=${few}`;
        sheet.rel = 'stylesheet';
        document.body.appendChild(sheet);
      }
    }
  }
});

new Vue({
  el: '#app',
  template: '<app />'
});
