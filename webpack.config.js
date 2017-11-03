const path = require('path');
const pkg = require('./package.json');
const webpack = require('webpack');

const HtmlWebpackPlugin = require('html-webpack-plugin');
const CleanWebpackPlugin = require('clean-webpack-plugin');
const PrettierPlugin = require('prettier-webpack-plugin');

const dist = path.resolve(__dirname, 'assets/dist');

module.exports = {
  entry: {
    index: './assets/index.js'
  },
  plugins: [
    new PrettierPlugin(pkg.prettier),
    new CleanWebpackPlugin([dist]),
    new HtmlWebpackPlugin({
      template: 'assets/index.html',
      favicon: 'assets/favicon.png'
    })
  ],
  output: {
    filename: '[name].[hash].js',
    path: dist
  },
  resolve: {
    alias: {
      vue$: 'vue/dist/vue.esm.js'
    }
  },
  module: {
    rules: [
      {
        test: /\.js$/,
        exclude: /node_modules/,
        loader: 'babel-loader',
        options: {
          presets: ['babel-preset-env']
        }
      },
      {
        test: /\.(png|jpg|gif|svg)$/,
        loader: 'file-loader',
        options: {
          name: '[name].[ext]?[hash]'
        }
      }
    ]
  },
  devtool: '#eval-source-map'
};

if (process.env.NODE_ENV === 'production') {
  module.exports.devtool = '#source-map';
  // http://vue-loader.vuejs.org/en/workflow/production.html
  module.exports.plugins = (module.exports.plugins || []).concat([
    new webpack.DefinePlugin({
      'process.env': {
        NODE_ENV: '"production"'
      }
    }),
    new webpack.optimize.UglifyJsPlugin({
      sourceMap: true,
      compress: {
        warnings: false
      }
    }),
    new webpack.LoaderOptionsPlugin({
      minimize: true
    })
  ]);
}
