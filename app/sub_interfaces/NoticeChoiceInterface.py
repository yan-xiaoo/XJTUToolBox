from __future__ import annotations

from collections import OrderedDict, defaultdict

from PyQt5.QtCore import QSize, QSignalBlocker, Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    PrimaryPushButton,
    SearchLineEdit,
    TitleLabel,
    ToolTipFilter,
    TransparentToolButton,
    TreeWidget,
    isDarkTheme,
    qconfig,
)

from app.search import fuzzy_score
from notification import NotificationManager, Ruleset
from notification.filter import TagIncludeFilter
from notification.source import source_registry


class NoticeChoiceInterface(QFrame):
    """Stable, searchable source tree with site-level tri-state selection."""

    ACTION_COLUMN_WIDTH = 106
    STATUS_COLUMN_WIDTH = 160
    ACTION_BUTTON_SIZE = 32
    ACTION_SPACING = 6
    QUICK_CATEGORY_PREFIX = "通知分类 · "

    quit = pyqtSignal()
    setRuleClicked = pyqtSignal(str)

    def __init__(self, manager: NotificationManager, main_window, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.main_window = main_window
        self.setObjectName("NoticeChoiceInterface")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(520, 420)

        self.sourceItems: dict[str, QTreeWidgetItem] = {}
        self.siteItems: dict[str, QTreeWidgetItem] = {}
        self.siteChannels: dict[str, list[str]] = {}
        self.ruleButtons: dict[str, TransparentToolButton] = {}
        self._sourceSearchValues: dict[str, tuple[object, ...]] = {}
        self._siteSearchValues: dict[str, tuple[object, ...]] = {}
        self._sourceItemCopies: dict[str, list[QTreeWidgetItem]] = defaultdict(list)
        self._siteItemCopies: dict[str, list[QTreeWidgetItem]] = defaultdict(list)
        self._siteChannelsByItem: dict[int, list[str]] = {}
        self._sourceSearchValuesByItem: dict[int, tuple[object, ...]] = {}
        self._siteSearchValuesByItem: dict[int, tuple[object, ...]] = {}
        self._ruleButtonCopies: dict[str, list[TransparentToolButton]] = defaultdict(list)
        self._classificationItemCopies: dict[tuple[str, str], list[QTreeWidgetItem]] = defaultdict(list)
        self._classificationSearchValuesByItem: dict[int, tuple[object, ...]] = {}

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(24, 18, 24, 18)
        self.vBoxLayout.setSpacing(12)

        headerLayout = QHBoxLayout()
        self.label = TitleLabel(self.tr("选择需要查询的网站"), self)
        self.selectionLabel = CaptionLabel(self)
        headerLayout.addWidget(self.label)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.selectionLabel, alignment=Qt.AlignBottom)
        self.vBoxLayout.addLayout(headerLayout)

        self.searchEdit = SearchLineEdit(self)
        self.searchEdit.setPlaceholderText(self.tr("搜索学院、书院、部门、学科或栏目"))
        self.searchEdit.setClearButtonEnabled(True)
        self.searchEdit.setFixedHeight(38)
        self.searchEdit.textChanged.connect(self.onSearchChanged)
        self.vBoxLayout.addWidget(self.searchEdit)

        # TreeWidget is itself a scroll area.  Keeping it in the stretch slot
        # makes expansion affect only its viewport, never the header/search bar.
        self.tree = TreeWidget(self)
        self.tree.setObjectName("noticeSourceTree")
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([self.tr("来源与栏目"), self.tr("状态"), self.tr("操作")])
        self.tree.setAlternatingRowColors(False)
        self.tree.setAnimated(True)
        self.tree.setIndentation(24)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.tree.header().setSectionResizeMode(2, QHeaderView.Fixed)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().resizeSection(1, self.STATUS_COLUMN_WIDTH)
        self.tree.header().resizeSection(2, self.ACTION_COLUMN_WIDTH)
        self.vBoxLayout.addWidget(self.tree, stretch=1)

        self.returnButton = PrimaryPushButton(FluentIcon.ACCEPT, self.tr("完成"), self)
        self.returnButton.setFixedWidth(132)
        self.returnButton.clicked.connect(self.onReturnButtonClicked)
        self.vBoxLayout.addWidget(self.returnButton, alignment=Qt.AlignRight)

        self._buildTree()
        self.tree.itemChanged.connect(self.onItemChanged)
        self.tree.itemDoubleClicked.connect(self.onItemDoubleClicked)
        qconfig.themeChanged.connect(self._applyThemeSurface)
        self._applyThemeSurface()
        self._updateSelectionLabel()

    @pyqtSlot()
    def _applyThemeSurface(self, *_args) -> None:
        background = "#202020" if isDarkTheme() else "#F3F3F3"
        self.setStyleSheet(
            f"QFrame#NoticeChoiceInterface {{ background-color: {background}; }}"
        )

    def _buildTree(self) -> None:
        hierarchy: OrderedDict = OrderedDict()
        for source in source_registry.sources():
            for placement_index, placement in enumerate(source.directory_placements):
                site_key = (source.site_id, placement_index, placement.name)
                hierarchy.setdefault(source.root_group, OrderedDict()) \
                    .setdefault(placement.category, OrderedDict()) \
                    .setdefault(placement.discipline, OrderedDict()) \
                    .setdefault(site_key, []).append(source.id)

        known_ids = {source.id for source in source_registry.sources()}
        unknown_ids = [one for one in self.manager.subscription if one not in known_ids]
        for source_id in unknown_ids:
            hierarchy.setdefault(self.tr("已保留的旧配置"), OrderedDict()) \
                .setdefault(self.tr("未知来源"), OrderedDict()) \
                .setdefault("", OrderedDict()) \
                .setdefault((f"unknown:{source_id}", 0, source_id), []).append(source_id)

        for root_name, categories in hierarchy.items():
            rootItem = QTreeWidgetItem(self.tree, [root_name, "", ""])
            rootItem.setFlags(Qt.ItemIsEnabled)
            # The school root is visible on entry; every nested folder starts
            # collapsed. Search can still expand a matching path temporarily.
            rootItem.setExpanded(root_name == "西安交通大学")
            for category_name, disciplines in categories.items():
                categoryItem = QTreeWidgetItem(rootItem, [category_name, "", ""])
                categoryItem.setFlags(Qt.ItemIsEnabled)
                categoryItem.setExpanded(False)
                for discipline_name, sites in disciplines.items():
                    if discipline_name:
                        disciplineItem = QTreeWidgetItem(categoryItem, [discipline_name, "", ""])
                        disciplineItem.setFlags(Qt.ItemIsEnabled)
                        disciplineItem.setExpanded(False)
                        siteParent = disciplineItem
                    else:
                        siteParent = categoryItem
                    for site_key, source_ids in sites.items():
                        self._addSite(
                            siteParent,
                            site_key,
                            source_ids,
                            root_name,
                            category_name,
                            discipline_name,
                        )

    def _addSite(
        self,
        parent: QTreeWidgetItem,
        site_key: tuple[str, int, str],
        source_ids: list[str],
        root_name: str,
        category_name: str,
        discipline_name: str,
    ) -> None:
        site_id, placement_index, placement_name = site_key
        first = source_registry.get(source_ids[0])
        site_name = placement_name if first is not None else source_ids[0]
        self.siteChannels.setdefault(site_id, list(source_ids))

        # A site with only one feed is one selectable unit.  Rendering an extra
        # "教务处 → 教学通知" parent/child pair adds no choice and was the
        # classification defect shown by the user.  Keep multi-feed sites as
        # tri-state parents, but flatten a single feed into its directory row.
        if len(source_ids) == 1:
            self._addSourceItem(
                parent,
                source_ids[0],
                site_name,
                root_name,
                category_name,
                discipline_name,
                site_name,
                show_channel_in_status=False,
            )
            return

        siteItem = QTreeWidgetItem(parent, [site_name, self.tr(f"{len(source_ids)} 个栏目"), ""])
        siteItem.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
        siteItem.setData(0, Qt.UserRole, ("site", site_id, placement_index))
        siteItem.setExpanded(False)
        self.siteItems.setdefault(site_id, siteItem)
        self._siteSearchValues.setdefault(
            site_id, (root_name, category_name, discipline_name, site_name)
        )
        self._siteItemCopies[site_id].append(siteItem)
        self._siteChannelsByItem[id(siteItem)] = list(source_ids)
        self._siteSearchValuesByItem[id(siteItem)] = (
            root_name,
            category_name,
            discipline_name,
            site_name,
        )

        for source_id in source_ids:
            descriptor = source_registry.get(source_id)
            channel_name = descriptor.channel_name if descriptor is not None else source_id
            self._addSourceItem(
                siteItem,
                source_id,
                channel_name,
                root_name,
                category_name,
                discipline_name,
                site_name,
                show_channel_in_status=False,
            )
        self._refreshSiteState(siteItem)

    def _addSourceItem(
        self,
        parent: QTreeWidgetItem,
        source_id: str,
        display_name: str,
        root_name: str,
        category_name: str,
        discipline_name: str,
        site_name: str,
        *,
        show_channel_in_status: bool,
    ) -> None:
        descriptor = source_registry.get(source_id)
        channel_name = descriptor.channel_name if descriptor is not None else source_id
        available = descriptor is not None and descriptor.verified
        checked = source_id in self.manager.subscription
        if descriptor is None:
            state_text = self.tr("未知·可取消")
        elif descriptor.status == "empty":
            state_text = self.tr("当前为空")
        elif not descriptor.verified:
            state_text = self.tr("待核验")
        else:
            state_text = self.tr("可用")
        if show_channel_in_status and descriptor is not None:
            state_text = f"{channel_name} · {state_text}"
        if descriptor is not None and descriptor.filter_categories:
            state_text += self.tr(f" · {len(descriptor.filter_categories)} 个分类")
        item = QTreeWidgetItem(parent, [display_name, state_text, ""])
        flags = Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
        if available or checked:
            flags |= Qt.ItemIsEnabled
        item.setFlags(flags)
        item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
        item.setData(0, Qt.UserRole, ("source", source_id))
        item.setExpanded(False)
        self._setItemSizeHint(item)
        if descriptor is not None:
            item.setToolTip(0, descriptor.url)
        search_values = (
            root_name,
            category_name,
            discipline_name,
            site_name,
            channel_name,
            descriptor.url if descriptor is not None else source_id,
            *(() if descriptor is None else descriptor.tags),
            *(() if descriptor is None else descriptor.filter_categories),
        )
        self.sourceItems.setdefault(source_id, item)
        self._sourceSearchValues.setdefault(source_id, search_values)
        self._sourceItemCopies[source_id].append(item)
        self._sourceSearchValuesByItem[id(item)] = search_values
        self._installActions(item, source_id, available, checked)
        if descriptor is not None:
            for tag in descriptor.filter_categories:
                self._addClassificationItem(item, source_id, tag, checked)

    def _addClassificationItem(
        self,
        parent: QTreeWidgetItem,
        source_id: str,
        tag: str,
        source_checked: bool,
    ) -> None:
        selected = bool(self._quickCategoryRules(source_id, tag))
        item = QTreeWidgetItem(parent, [tag, self.tr("通知分类"), ""])
        flags = Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
        if source_checked:
            flags |= Qt.ItemIsEnabled
        item.setFlags(flags)
        item.setCheckState(0, Qt.Checked if selected else Qt.Unchecked)
        item.setData(0, Qt.UserRole, ("classification", source_id, tag))
        item.setToolTip(0, self.tr(f"只保留该页面标记为“{tag}”的通知"))
        self._setItemSizeHint(item)
        values = (source_id, tag, "通知分类")
        self._classificationItemCopies[(source_id, tag)].append(item)
        self._classificationSearchValuesByItem[id(item)] = values

    def _quickCategoryRules(self, source_id: str, tag: str) -> list[Ruleset]:
        name = self.QUICK_CATEGORY_PREFIX + tag
        return [
            ruleset
            for ruleset in self.manager.ruleset.get(source_id, ())
            if ruleset.name == name
            and len(ruleset.filters) == 1
            and isinstance(ruleset.filters[0], TagIncludeFilter)
            and ruleset.filters[0].tag == tag
        ]

    def _setItemSizeHint(self, item: QTreeWidgetItem) -> None:
        height = max(40, self.tree.fontMetrics().height() + 18)
        for column in range(self.tree.columnCount()):
            item.setSizeHint(column, QSize(0, height))

    def _installActions(
        self,
        item: QTreeWidgetItem,
        source_id: str,
        available: bool,
        checked: bool,
    ) -> None:
        container = QWidget(self.tree)
        container.setMinimumSize(
            2 * self.ACTION_BUTTON_SIZE + self.ACTION_SPACING,
            self.ACTION_BUTTON_SIZE,
        )
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(self.ACTION_SPACING)
        layout.setAlignment(Qt.AlignCenter)
        browse = TransparentToolButton(FluentIcon.LINK, container)
        browse.setFixedSize(self.ACTION_BUTTON_SIZE, self.ACTION_BUTTON_SIZE)
        browse.setToolTip(self.tr("打开官网"))
        browse.installEventFilter(ToolTipFilter(browse))
        browse.setEnabled(bool(source_registry.get(source_id)))
        browse.clicked.connect(lambda _=False, sid=source_id: self._openSource(sid))
        rule = TransparentToolButton(FluentIcon.FILTER, container)
        rule.setFixedSize(self.ACTION_BUTTON_SIZE, self.ACTION_BUTTON_SIZE)
        rule.setToolTip(self.tr("设置过滤规则"))
        rule.installEventFilter(ToolTipFilter(rule))
        rule.setEnabled(available and checked)
        rule.clicked.connect(lambda _=False, sid=source_id: self.setRuleClicked.emit(sid))
        layout.addWidget(browse)
        layout.addWidget(rule)
        self.tree.setItemWidget(item, 2, container)
        self.ruleButtons.setdefault(source_id, rule)
        self._ruleButtonCopies[source_id].append(rule)

    def _refreshSiteState(self, siteItem: QTreeWidgetItem) -> None:
        states = [
            siteItem.child(index).checkState(0)
            for index in range(siteItem.childCount())
            if (siteItem.child(index).data(0, Qt.UserRole) or (None,))[0] == "source"
        ]
        if states and all(state == Qt.Checked for state in states):
            state = Qt.Checked
        elif states and all(state == Qt.Unchecked for state in states):
            state = Qt.Unchecked
        else:
            state = Qt.PartiallyChecked
        blocker = QSignalBlocker(self.tree)
        siteItem.setCheckState(0, state)
        del blocker

    def _writeSubscription(self, source_id: str, checked: bool) -> None:
        if checked and source_id not in self.manager.subscription:
            self.manager.add_subscription(source_id)
        elif not checked and source_id in self.manager.subscription:
            self.manager.remove_subscription(source_id, remove_ruleset=False)
        descriptor = source_registry.get(source_id)
        for button in self._ruleButtonCopies.get(source_id, ()):
            button.setEnabled(bool(checked and descriptor is not None and descriptor.verified))
        for (one_source, _tag), items in self._classificationItemCopies.items():
            if one_source != source_id:
                continue
            for item in items:
                flags = item.flags()
                item.setFlags(flags | Qt.ItemIsEnabled if checked else flags & ~Qt.ItemIsEnabled)

    def _setSourceChecked(self, source_id: str, checked: bool) -> None:
        """Mirror one stable subscription across every directory placement."""

        state = Qt.Checked if checked else Qt.Unchecked
        blocker = QSignalBlocker(self.tree)
        for child in self._sourceItemCopies.get(source_id, ()):
            child.setCheckState(0, state)
        del blocker
        self._writeSubscription(source_id, checked)
        parents = {
            id(child.parent()): child.parent()
            for child in self._sourceItemCopies.get(source_id, ())
            if child.parent() is not None
        }
        for parent in parents.values():
            payload = parent.data(0, Qt.UserRole)
            if payload and payload[0] == "site":
                self._refreshSiteState(parent)

    def _setClassificationChecked(self, source_id: str, tag: str, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        blocker = QSignalBlocker(self.tree)
        for item in self._classificationItemCopies.get((source_id, tag), ()):
            item.setCheckState(0, state)
        del blocker
        rules = self._quickCategoryRules(source_id, tag)
        if checked and not rules and source_id in self.manager.subscription:
            self.manager.add_ruleset(
                source_id,
                Ruleset(
                    TagIncludeFilter(tag),
                    name=self.QUICK_CATEGORY_PREFIX + tag,
                    enable=True,
                ),
            )
        elif not checked:
            for ruleset in rules:
                self.manager.remove_ruleset(source_id, ruleset)

    @pyqtSlot(QTreeWidgetItem, int)
    def onItemChanged(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        payload = item.data(0, Qt.UserRole)
        if not payload:
            return
        kind, identifier, *_ = payload
        if kind == "source":
            self._setSourceChecked(identifier, item.checkState(0) == Qt.Checked)
        elif kind == "classification":
            self._setClassificationChecked(
                identifier,
                payload[2],
                item.checkState(0) == Qt.Checked,
            )
        elif kind == "site":
            state = item.checkState(0)
            # PartiallyChecked is a derived display state, not a request to
            # clear siblings.
            if state == Qt.PartiallyChecked:
                self._updateSelectionLabel()
                return
            checked = state == Qt.Checked
            for index in range(item.childCount()):
                child = item.child(index)
                child_payload = child.data(0, Qt.UserRole)
                if child_payload and child_payload[0] == "source" and child.flags() & Qt.ItemIsEnabled:
                    self._setSourceChecked(child_payload[1], checked)
        self._updateSelectionLabel()

    @pyqtSlot(QTreeWidgetItem, int)
    def onItemDoubleClicked(self, item: QTreeWidgetItem, _column: int) -> None:
        payload = item.data(0, Qt.UserRole)
        if not payload:
            item.setExpanded(not item.isExpanded())
            return
        kind, identifier, *_ = payload
        if kind == "source":
            if item.childCount():
                item.setExpanded(not item.isExpanded())
            else:
                self._openSource(identifier)
        elif kind == "site":
            descriptor = next(
                (
                    source_registry.get(one)
                    for one in self._siteChannelsByItem.get(id(item), ())
                ),
                None,
            )
            if descriptor is not None:
                QDesktopServices.openUrl(QUrl(descriptor.home))

    def _openSource(self, source_id: str) -> None:
        descriptor = source_registry.get(source_id)
        if descriptor is not None:
            QDesktopServices.openUrl(QUrl(descriptor.url))

    def _updateSelectionLabel(self) -> None:
        selected = sum(one in self.manager.subscription for one in self.sourceItems)
        classifications = sum(
            bool(self._quickCategoryRules(source_id, tag))
            for source_id, tag in self._classificationItemCopies
        )
        suffix = self.tr(f" · {classifications} 个分类筛选") if classifications else ""
        self.selectionLabel.setText(
            self.tr(f"已选 {selected} / {len(self.sourceItems)} 个栏目") + suffix
        )

    @pyqtSlot(str)
    def onSearchChanged(self, query: str) -> None:
        has_query = bool(query.strip())

        def values_for(item: QTreeWidgetItem) -> tuple[object, ...]:
            payload = item.data(0, Qt.UserRole)
            if not payload:
                return (item.text(0),)
            kind = payload[0]
            if kind == "site":
                return self._siteSearchValuesByItem.get(id(item), (item.text(0),))
            if kind == "source":
                return self._sourceSearchValuesByItem.get(id(item), (item.text(0),))
            if kind == "classification":
                return self._classificationSearchValuesByItem.get(id(item), (item.text(0),))
            return (item.text(0),)

        def visit(item: QTreeWidgetItem, ancestor_match: bool = False) -> bool:
            own_match = not has_query or fuzzy_score(query, values_for(item)) is not None
            inherited = ancestor_match or (has_query and own_match)
            child_visible = False
            for index in range(item.childCount()):
                child_visible = visit(item.child(index), inherited) or child_visible
            visible = not has_query or inherited or child_visible
            item.setHidden(not visible)
            if has_query and child_visible:
                item.setExpanded(True)
            return visible

        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))

    @pyqtSlot()
    def onReturnButtonClicked(self) -> None:
        self.quit.emit()
