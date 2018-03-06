import Vue from 'vue';
import { call } from './utils.js';
import tpl from './msgs.html';

export default function(params) {
  let loader = new Loader({ propsData: params });
  loader.load();
  return loader;
}

let Loader = Vue.extend({
  template: tpl,
  props: {
    cls: { type: String, required: true },
    query: { type: String, required: true },
    open: { type: Function, required: true },
    pics: { type: Function, required: true }
  },
  data: function() {
    return {
      name: 'loader',
      loading: false,
      error: null
    };
  },
  methods: {
    load: function() {
      this.error = null;
      this.search().then(res => {
        if (res.errors) {
          this.error = res.errors;
          this.mount();
          return this;
        }
        let data = { propsData: Object.assign(res, this.$props) };
        this.view = res.thread ? new Thread(data) : new Msgs(data);
      });
    },
    call: function(method, url, data, headers = null) {
      window.app.refreshTags();

      this.loading = true;
      return call(method, url, data, headers).then(res => {
        this.loading = false;
        if (res.errors) {
          this.error = res.errors;
          return res;
        }
        return res;
      });
    },
    search: function(preload = undefined) {
      return this.call('post', '/search', { q: this.query, preload: preload });
    },
    mount: function() {
      this.$mount(`.${this.cls}`);
    },
    newQuery: function(q) {
      if (this.view) {
        this.view.newQuery(q);
        return;
      }
      if (q) {
        this.query = q;
      }
      this.error = null;
      this.loading = true;
    }
  }
});

let Base = {
  template: tpl,
  mixins: [Loader],
  props: {
    uids: { type: Array, required: true },
    msgs: { type: Object, required: true },
    msgs_info: { type: String, required: true },
    tags: { type: Array, default: () => [] }
  },
  created: function() {
    this.mount();
    this.pics(this.msgs);
  },
  data: function() {
    return {
      bodies: {}
    };
  },
  computed: {
    loaded: function() {
      return this.uids.filter(i => this.msgs[i]);
    },
    hidden: function() {
      return this.uids.filter(i => !this.msgs[i]);
    }
  },
  methods: {
    refresh: function(preload = undefined) {
      let data = { uids: this.loaded, hide_tags: this.tags };
      this.search(preload).then(res => {
        if (res.errors) {
          return;
        }
        this.set(res);
        data.uids = data.uids.filter(item => !res.msgs[item]);
        if (data.uids.length > 0) {
          this.call('post', this.msgs_info, data).then(this.setMsgs);
        }
      });
    },
    setMsgs: function(msgs) {
      this.msgs = Object.assign({}, this.msgs, msgs);
      this.pics(msgs);
    },
    fetchBodies: function(uids) {
      let data = { uids: uids, fix_privacy: window.app.opts.fixPrivacy };
      return this.call('post', '/msgs/body', data).then(res => {
        this.bodies = Object.assign({}, this.bodies, res);
        this.refresh();
      });
    },
    archive: function() {
      return this.editTags({ old: ['#inbox'] });
    },
    del: function() {
      return this.editTags({ new: ['#trash'] });
    }
  }
};

let Msgs = Vue.extend({
  mixins: [Base],
  props: {
    threads: { type: Boolean, default: false }
  },
  data: function() {
    return {
      name: 'msgs',
      perPage: 200,
      picked: [],
      detailed: null,
      opened: null
    };
  },
  computed: {
    allTags: function() {
      if (!this.uids.length) {
        return [];
      }
      let tags = this.tags ? this.tags.slice() : [];
      for (let i of this.picked) {
        tags.push.apply(tags, this.msgs[i].tags);
      }
      return [...new Set(tags)];
    }
  },
  methods: {
    clean: function(q) {
      this.query = q;
      this.loading = true;
    },
    set: function(res) {
      this.uids = res.uids;
      this.tags = res.tags;
      this.setMsgs(res.msgs);
    },
    pick: function(uid) {
      let idx = this.picked.indexOf(uid);
      if (idx == -1) {
        this.picked.push(uid);
      } else {
        this.picked.splice(idx, 1);
      }
    },
    picker: function(name) {
      switch (name) {
        case 'all':
          this.picked = this.loaded;
          break;
        case 'read':
          this.picked = this.loaded.filter(i => !this.msgs[i].is_unread);
          break;
        case 'unread':
          this.picked = this.loaded.filter(i => this.msgs[i].is_unread);
          break;
        case 'none':
          this.picked = [];
          break;
      }
    },
    link: function() {
      this.call('post', '/thrs/link', { uids: this.picked }).then(() => {
        this.picked = [];
        this.refresh();
      });
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
      return this.call('post', this.msgs_info, {
        uids: uids,
        hide_tags: this.tags
      }).then(this.setMsgs);
    },
    details: function(uid) {
      if (this.detailed == uid) {
        this.detailed = null;
      } else {
        this.detailed = uid;
      }
    },
    openMsg: function(uid) {
      if (this.threads) {
        return this.open(this.msgs[uid].query_thread);
      }
      let msg = this.msgs[uid];
      if (msg.count == 1) {
        this.fetchBodies([uid]);
      }
      if (this.opened == uid) {
        this.opened = null;
      } else {
        this.opened = uid;
        this.$nextTick(() => {
          let opened = this.$el.querySelector('.msg--opened');
          if (!opened) {
            return;
          }
          let box = this.$refs.msgs;
          if (box.clientHeight == box.scrollHeight) {
            return;
          }
          // opened.scrollIntoView()
          let top = opened.offsetTop - 50;
          if (top < box.scrollTop) {
            box.scrollTop = top;
          }
        });
      }
    },
    editTags: function(opts, picked = null) {
      picked = picked || this.picked;

      let uids;
      if (!opts['new'] && opts.old.indexOf('\\Seen') != -1) {
        uids = picked;
      } else if (!opts.old && opts['new'].indexOf('\\Flagged') != -1) {
        uids = picked;
      } else if (!this.threads) {
        uids = picked;
      } else {
        uids = [];
        for (let i of picked) {
          uids.push.apply(uids, this.msgs[i].uids);
        }
      }

      opts = Object.assign({ uids: uids }, opts);
      return this.call('post', '/msgs/flag', opts).then(res => {
        if (!res.errors) {
          this.refresh();
        }
      });
    }
  }
});

let Thread = Vue.extend({
  mixins: [Base],
  props: {
    tags: { type: Array, required: true },
    same_subject: { type: Array, required: true },
    edit: { type: Object }
  },
  data: function() {
    return {
      name: 'thread',
      preload: 4,
      detailed: [],
      opened: [],
      pickerOpts: {
        unread: 'Mark all as unread',
        read: 'Mark all as read',
        collapse: 'Collapse all',
        expand: 'Expand all'
      }
    };
  },
  created: function() {
    if (!this.threads && this.uids.length == 1) {
      this.openMsg(this.uids[0]);
    }
    if (this.edit && this.opened.indexOf(this.edit.uid) == -1) {
      this.openMsg(this.edit.uid);
    }
  },
  methods: {
    set: function(res) {
      this.uids = res.uids;
      this.tags = res.tags;
      this.edit = res.edit;
      this.setMsgs(res.msgs);
    },
    loadAll: function() {
      return this.call('post', this.msgs_info, {
        uids: this.hidden,
        hide_tags: this.tags
      }).then(this.setMsgs);
    },
    details: function(uid) {
      let idx = this.detailed.indexOf(uid);
      if (idx == -1) {
        this.detailed.push(uid);
      } else {
        this.detailed.splice(idx, 1);
      }
    },
    openMsg: function(uid, force) {
      this.fetchBodies([uid]);
      let idx = this.opened.indexOf(uid);
      if (idx == -1) {
        this.opened.push(uid);
      } else if (!force) {
        this.opened.splice(idx, 1);
      }
    },
    openInSplit: function() {
      window.app.openInSplit(this.query);
    },
    editTags: function(opts, picked = null) {
      let preload = this.hidden.length > 0 ? this.preload : null;
      opts = Object.assign({ uids: picked || this.uids }, opts);
      return this.call('post', '/msgs/flag', opts).then(res => {
        if (!res.errors) {
          this.refresh(preload);
        }
      });
    },
    picker: function(name) {
      switch (name) {
        case 'unread':
          this.editTags({ old: ['\\Seen'] }, this.uids);
          break;
        case 'read':
          this.editTags({ new: ['\\Seen'] }, this.uids);
          break;
        case 'collapse':
          this.opened = [];
          break;
        case 'expand':
          this.fetchBodies(this.uids);
          this.opened = this.uids;
          if (this.hidden.length) {
            this.loadAll();
          }
          break;
      }
    }
  }
});
