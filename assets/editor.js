import Vue from 'vue';
import { call } from './utils.js';
import { Slider } from './slider.js';
import tpl from './editor.html';

Vue.component('editor', {
  template: tpl,
  props: {
    msg: { type: Object, required: true },
    refresh: { type: Function, required: true },
    cancel: { type: Function, required: true }
  },
  data: function() {
    return {
      edit: true,
      html: ''
    };
  },
  methods: {
    save: function(e) {
      let input = e.target;
      let data = new FormData();
      data.append('uid', this.msg.uid);
      for (let i of ['from', 'to', 'subject', 'txt']) {
        data.append(i, this.$refs[i].value);
      }
      for (let file of Array.from(input.files || [])) {
        data.append('files', file, file.name);
      }
      call('post', '/editor', data, {}).then(() => this.refresh());
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
    }
  }
});
