import Vue from 'vue';
import { call } from './utils.js';
import { Slider } from './slider.js';
import tpl from './editor.html';

Vue.component('editor', {
  template: tpl,
  props: {
    msg: { type: Object, required: true },
    query: { type: Function, required: true },
    refresh: { type: Function, required: true },
    cancel: { type: Function, required: true }
  },
  data: function() {
    return {
      edit: true,
      countdown: null,
      html: ''
    };
  },
  methods: {
    save: function() {
      let data = new FormData();
      data.append('uid', this.msg.uid);
      for (let i of ['from', 'to', 'subject', 'txt']) {
        data.append(i, this.$refs[i].value);
      }
      for (let file of Array.from(this.$refs.upload.files || [])) {
        data.append('files', file, file.name);
      }
      return call('post', '/editor', data, {}).then(res => {
        this.refresh();
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
      this.edit = false;
      call('post', '/markdown', { txt: this.$refs.txt.value }).then(
        res => (this.html = res)
      );
    },
    send: function() {
      this.preview();
      this.countdown = 5;
      this.sending();
    },
    sending: function() {
      if (this.countdown > 0) {
        this.countdown = this.countdown - 1;
        setTimeout(() => this.sending(), 1000);
      } else if (this.countdown == 0) {
        call('get', this.msg.url_send).then(res => this.query(res.query));
      } else {
        this.countdown = null;
      }
    }
  }
});
