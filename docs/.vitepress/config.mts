import { defineConfig } from 'vitepress'

import { withMermaid } from "vitepress-plugin-mermaid";

const customElements = [
	'mjx-container',
    'mjx-assistive-mml',
	'math',
	'maction',
	'maligngroup',
	'malignmark',
	'menclose',
	'merror',
	'mfenced',
	'mfrac',
	'mi',
	'mlongdiv',
	'mmultiscripts',
	'mn',
	'mo',
	'mover',
	'mpadded',
	'mphantom',
	'mroot',
	'mrow',
	'ms',
	'mscarries',
	'mscarry',
	'mscarries',
	'msgroup',
	'mstack',
	'mlongdiv',
	'msline',
	'mstack',
	'mspace',
	'msqrt',
	'msrow',
	'mstack',
	'mstack',
	'mstyle',
	'msub',
	'msup',
	'msubsup',
	'mtable',
	'mtd',
	'mtext',
	'mtr',
	'munder',
	'munderover',
	'semantics',
	'math',
	'mi',
	'mn',
	'mo',
	'ms',
	'mspace',
	'mtext',
	'menclose',
	'merror',
	'mfenced',
	'mfrac',
	'mpadded',
	'mphantom',
	'mroot',
	'mrow',
	'msqrt',
	'mstyle',
	'mmultiscripts',
	'mover',
	'mprescripts',
	'msub',
	'msubsup',
	'msup',
	'munder',
	'munderover',
	'none',
	'maligngroup',
	'malignmark',
	'mtable',
	'mtd',
	'mtr',
	'mlongdiv',
	'mscarries',
	'mscarry',
	'msgroup',
	'msline',
	'msrow',
	'mstack',
	'maction',
	'semantics',
	'annotation',
	'annotation-xml',
];

// https://vitepress.dev/reference/site-config
export default withMermaid(defineConfig({
  vite: {
    optimizeDeps: {
      exclude: [
        '@nolebase/vitepress-plugin-enhanced-readabilities/client',
        'vitepress',
        '@nolebase/ui',
      ],
    },
    ssr: {
      noExternal: [
        // 如果还有别的依赖需要添加的话，并排填写和配置到这里即可
        '@nolebase/vitepress-plugin-enhanced-readabilities',
        '@nolebase/ui',
      ],
    }
  },
  title: "XJTUToolBox 文档",
  description: "使用说明与开发教程",
  base: '/',
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    sidebarMenuLabel:'目录',
    returnToTopLabel:'返回顶部',
    lastUpdated: {
      text: '上次更新于',
      formatOptions: {
        dateStyle: 'full',
        timeStyle: 'medium'
      },
    },
    footer: {
      message: 'Released under the GPL-3.0 License.',
      copyright: 'Copyright © 2025 present yan-xiaoo',
    },
    docFooter: {
      prev: '上一页',
      next: '下一页',
    },
    editLink: {
      pattern: 'https://github.com/yan-xiaoo/XJTUToolBox/edit/main/docs/:path', // 改成自己的仓库
      text: '在 GitHub 编辑本页'
    },
    outline: {
      level: 'deep', // 显示2-6级标题
      label: '目录' // 文字显示
    },
    // logo: {
    //   src: '/DX_logo_black.svg',
    //   alt: 'Logo: XJTU-RMV',
    // },
    nav: [
      { text: '主页', link: '/' },
      { text: '用户手册', link: '/tutorial/quick-start' },
      { text: '开发指南', link: '/development/setup' }
    ],

    sidebar: [
      {
        text: '用户手册',
        items: [
          { text: '快速开始', link: '/tutorial/quick-start' },
          { text: '常见问题', link: '/tutorial/faq' },
          { text: '登录与账户管理', link: '/tutorial/account' },
          { text: '课表与考勤', link: '/tutorial/schedule' },
          { text: '考勤流水', link: '/tutorial/attendance' },
          { text: '成绩查询与计算', link: '/tutorial/score' },
          { text: '一键评教', link: '/tutorial/judge'},
          { text: '通知查询', link: '/tutorial/notice'},
          { text: '定时查询', link: '/tutorial/scheduled-event' },
        ]
      },
      {
        text: '开发指南',
        items: [
          { text: '开发环境搭建', link: '/development/setup' }
        ]
      }
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/yan-xiaoo/XJTUToolBox' }
    ],
    search: {
        provider: 'local',
        options: {
        translations: {
          button: {
            buttonText: "搜索文档",
            buttonAriaLabel: "搜索文档",
          },
          modal: {
            noResultsText: "无法找到相关结果",
            resetButtonTitle: "清除查询条件",
            footer: {
              selectText: "选择",
              navigateText: "切换",
            },
          },
        },
      },
    }
  },
  markdown: {
    math: true,
    image: {
      lazyLoading: true
    }
  },
  vue: {
    template: {
      compilerOptions: {
        isCustomElement: (tag) => customElements.includes(tag),
      },
    },
  },
  lang: 'zh-CN',
  mermaid: {
  }
}))
