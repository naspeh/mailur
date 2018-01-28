import Vue from 'vue';
import tpl from './slider.html';

export let Slider = Vue.extend({
  template: tpl,
  props: {
    slides: { type: Array, required: true },
    index: { type: Number, default: 0 }
  },
  data: function() {
    return {
      slide: this.slides[this.index],
      loading: true
    };
  },
  created: function() {
    window.addEventListener('keyup', this.keyup);
  },
  methods: {
    keyup: function(e) {
      let fn = {
        32: this.next,
        39: this.next,
        37: this.prev,
        27: this.close
      }[e.keyCode];
      fn && fn();
    },
    close: function() {
      window.removeEventListener('keyup', this.keyup);
      this.slides = [];
    },
    prev: function(e, callback) {
      callback = callback || (i => i - 1);
      let i = this.slides.indexOf(this.slide);
      i = callback(i);
      if (i < 0) {
        this.slide = this.slides.slice(-1)[0];
      } else if (i > this.slides.length - 1) {
        this.slide = this.slides[0];
      } else {
        this.slide = this.slides[i];
      }
    },
    next: function(e) {
      this.prev(e, i => i + 1);
    },
    fix: function() {
      this.loading = false;
      let fix = (x, y) => (!y ? 0 : Math.round((x - y) / 2) + 'px');
      let box = this.$refs.img,
        img = box.firstElementChild;
      img.style.maxWidth = box.clientWidth;
      img.style.maxHeight = box.clientHeight;
      img.style.top = fix(box.clientHeight, img.clientHeight);
      img.style.left = fix(box.clientWidth, img.clientWidth);
    }
  }
});
