import Vue from 'vue';
import tpl from './msg-line.html';

Vue.component('msg-line', {
  template: tpl,
  props: {
    msg: { type: Object, required: true },
    open: { type: Function, required: true },
    fetch: { type: Function, required: true }
  }
});
