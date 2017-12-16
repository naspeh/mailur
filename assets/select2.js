import Vue from 'vue';
import tpl from './select2.html';

Vue.component('Select2', {
  template: tpl,
  props: {
    value: { type: String },
    options: { type: Array }
  },
  data: function() {
    return {
      filter: this.value,
      selected: this.value,
      active: false
    };
  },
  mounted: function() {
    window.addEventListener('click', this.blur);
  },
  destroyed: function() {
    window.removeEventListener('click', this.blur);
  },
  computed: {
    filtered: function() {
      if (this.filter == this.value) {
        return this.options;
      }

      let opts = [];
      for (let opt of this.options) {
        if (opt.toLowerCase().indexOf(this.filter.toLowerCase()) != -1) {
          opts.push(opt);
        }
      }
      return opts;
    }
  },
  methods: {
    blur: function(e) {
      if (e.target.className.indexOf('select2') != -1) {
        return;
      }
      this.set();
    },
    set: function(val, active = false) {
      val = val || this.selected;
      this.$emit('update:value', val);
      this.selected = val;
      this.filter = val;
      if (active) {
        this.activate();
      } else if (this.active) {
        this.active = false;
        this.$nextTick(() => this.$el.querySelector('.select2__input').blur());
      }
    },
    activate: function() {
      this.active = true;
      this.$nextTick(() => {
        let element = this.selectedOpt();
        for (let i = 0; i < 3; i++) {
          if (element.previousSibling) {
            element = element.previousSibling;
          }
        }
        element.scrollIntoView();
      });
    },
    selectedOpt: function() {
      return (
        this.$el.querySelector('.select2__opts__item--active') ||
        this.$el.querySelector('.select2__opts__item')
      );
    },
    select: function(key, count = 1) {
      if (!this.selectedOpt()) {
        return;
      }
      let val, idx;
      idx = this.filtered.indexOf(this.selectedOpt().dataset.value);
      for (let i = 0; i < count; i++) {
        idx = key == 'up' ? idx - 1 : idx + 1;
        if (idx < 0) {
          val = this.filtered[this.filtered.length - 1];
        } else if (idx > this.filtered.length - 1) {
          val = this.filtered[0];
        } else {
          val = this.filtered[idx];
        }
      }
      this.selected = val;
      this.activate();
    }
  }
});
