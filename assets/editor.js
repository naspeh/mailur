import Vue from 'vue';
import { Slider } from './slider.js';
import { contains } from './utils.js';
import tpl from './editor.html';

Vue.component('editor', {
  template: tpl,
  props: {
    msg: { type: Object, required: true },
    call: { type: Function, required: true },
    query: { type: Function, required: true },
    refresh: { type: Function, required: true }
  },
  data: function() {
    return {
      uid: this.msg.uid,
      saving: false,
      editing: true,
      countdown: null,
      html: '',
      from: this.msg.from,
      to: this.msg.to,
      subject: this.msg.subject,
      txt: this.msg.txt,
      allFrom: window.data.addrs_from,
      allTo: window.data.addrs_to,
      addrCurrent: ''
    };
  },
  created: function() {
    let data = window.localStorage.getItem(this.msg.draft_id);
    data = (data && JSON.parse(data)) || {};
    if (data && data.time > this.msg.time * 1000) {
      Object.assign(this, data);
    }
  },
  methods: {
    autosave: function() {
      let data = this.values();
      window.localStorage.setItem(this.msg.draft_id, JSON.stringify(data));
      setTimeout(() => this.saving || this.save(), 3000);
    },
    update: function(val, el) {
      let addrs = el.__vue__.$refs['input'].value.split(',');
      if (!this.addrCurrent) {
        this.addrCurrent = addrs.slice(-1).pop();
      }
      if (val && val.indexOf(',') == -1) {
        for (let i in addrs) {
          if (addrs[i] == this.addrCurrent) {
            addrs[i] = val;
          }
        }
      }
      addrs = addrs.map(i => i.trim());
      addrs = addrs.filter(i => i).join(', ');
      if (el.classList.contains('editor__to')) {
        if (val) {
          addrs += ', ';
        }
        this.to = addrs;
      } else {
        this.from = addrs;
      }
      this.autosave();
      this.addrCurrent = '';
      return addrs;
    },
    keyup: function(e) {
      if (!e) return;
      let length = 1;
      for (let i of e.target.value.split(',')) {
        this.addrCurrent = i;
        length += i.length;
        if (length > e.target.selectionStart) {
          break;
        }
      }
    },
    filter: function(val) {
      return contains(val, this.addrCurrent.trim());
    },
    del: function() {
      window.localStorage.removeItem(this.msg.draft_id);
      let data = new FormData();
      data.append('draft_id', this.msg.draft_id);
      data.append('delete', true);
      this.call('post', '/editor', data, {}).then(() =>
        this.query(this.msg.query_thread)
      );
    },
    values: function() {
      let values = {};
      for (let i of ['from', 'to', 'subject', 'txt']) {
        values[i] = this[i];
      }
      values.time = new Date().getTime();
      return values;
    },
    save: function(refresh = false) {
      this.saving = true;
      let data = new FormData();
      let values = this.values();
      for (let i in values) {
        data.append(i, values[i]);
      }
      for (let file of Array.from(this.$refs.upload.files || [])) {
        data.append('files', file, file.name);
      }
      data.append('draft_id', this.msg.draft_id);
      return this.call('post', '/editor', data, {}).then(res => {
        this.saving = false;
        this.uid = res.uid;
        if (this.uid) {
          if (window.app.main.query == this.msg.query_thread) {
            let main = window.app.main.view;
            main.openMsg(this.uid, true);
          }
        }
        refresh && this.refresh();
        return res;
      });
    },
    slide: function(e, idx) {
      e.preventDefault();
      new Slider({
        el: '.slider',
        propsData: {
          slides: this.msg.files.filter(i => i.image),
          index: idx
        }
      });
    },
    preview: function() {
      this.editing = false;
      this.call('post', '/markdown', { txt: this.txt }).then(
        res => (this.html = res)
      );
    },
    previewInMain: function() {
      window.app.main.open(this.msg.query_thread);
    },
    send: function() {
      this.preview();
      this.countdown = 5;
      this.save(false).then(() => this.sending(this.msg.url_send));
    },
    sending: function(url_send) {
      if (this.countdown > 0) {
        this.countdown = this.countdown - 1;
        setTimeout(() => this.sending(url_send), 1000);
      } else if (this.countdown == 0) {
        this.call('get', url_send).then(res => this.query(res.query));
      } else {
        this.countdown = null;
      }
    },
    edit: function() {
      this.editing = true;
      if (this.countdown) {
        this.countdown = null;
        this.refresh();
      }
    }
  }
});
